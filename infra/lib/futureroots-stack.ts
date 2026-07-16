import * as path from "path";
import * as cdk from "aws-cdk-lib";
import * as apigwv2 from "aws-cdk-lib/aws-apigatewayv2";
import { HttpLambdaIntegration } from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as rds from "aws-cdk-lib/aws-rds";
import * as s3 from "aws-cdk-lib/aws-s3";
import { FckNatInstanceProvider } from "cdk-fck-nat";
import { Construct } from "constructs";

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`Missing required env var ${name} (set it in infra/.env)`);
  return value;
}

export class FutureRootsStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const dbPassword = required("DB_PASSWORD");
    const jwtSecret = required("JWT_SECRET");
    const sesFrom = required("SES_FROM_ADDRESS");
    // Agora App Certificate: the secret that signs family-call RTC tokens.
    // Server-side only, never shipped to the client (the App ID is public).
    const agoraSecret = required("AGORA_SECRET");
    const webBaseUrl = process.env.WEB_BASE_URL ?? "http://localhost:3000";
    const extraOrigins = (process.env.EXTRA_ORIGINS ?? "")
      .split(",")
      .map((o) => o.trim())
      .filter(Boolean);
    const testnetWebUrl = "https://testnet.futureroots.app";
    const allOrigins = [
      ...new Set([webBaseUrl, "http://localhost:3000", testnetWebUrl, ...extraOrigins]),
    ];

    // --- Network: 2 AZs; egress via a fck-nat t4g.nano instance (~$3/mo,
    // vs $32/mo managed NAT) so the Lambda can reach Stripe/SES/AI APIs.
    // RDS stays in isolated subnets with no route out.
    const natProvider = new FckNatInstanceProvider({
      instanceType: ec2.InstanceType.of(ec2.InstanceClass.T4G, ec2.InstanceSize.NANO),
    });
    const vpc = new ec2.Vpc(this, "Vpc", {
      // 10.1/16 (was 10.0/16): forces clean VPC replacement when the subnet
      // layout changes — in-place layout edits collide on CIDR allocation
      ipAddresses: ec2.IpAddresses.cidr("10.1.0.0/16"),
      maxAzs: 2,
      natGatewayProvider: natProvider,
      natGateways: 1,
      subnetConfiguration: [
        { name: "ingress", subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 },
        { name: "app", subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS, cidrMask: 24 },
        { name: "db", subnetType: ec2.SubnetType.PRIVATE_ISOLATED, cidrMask: 24 },
      ],
    });
    natProvider.securityGroup.addIngressRule(
      ec2.Peer.ipv4(vpc.vpcCidrBlock),
      ec2.Port.allTraffic(),
      "VPC egress through NAT"
    );
    // Keep S3 on the free gateway path (media bytes bypass the NAT instance)
    vpc.addGatewayEndpoint("S3Endpoint", {
      service: ec2.GatewayVpcEndpointAwsService.S3,
    });

    // --- Database: smallest real Postgres, never publicly reachable
    const dbSecurityGroup = new ec2.SecurityGroup(this, "DbSg", { vpc });
    // "Db2" (not "Db"): logical-id change forces clean replacement after the
    // VPC swap — RDS can't move a subnet group across VPCs in place
    const db = new rds.DatabaseInstance(this, "Db2", {
      engine: rds.DatabaseInstanceEngine.postgres({
        version: rds.PostgresEngineVersion.VER_16,
      }),
      instanceType: ec2.InstanceType.of(ec2.InstanceClass.T4G, ec2.InstanceSize.MICRO),
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      securityGroups: [dbSecurityGroup],
      allocatedStorage: 20,
      storageType: rds.StorageType.GP3,
      databaseName: "futureroots",
      credentials: rds.Credentials.fromPassword(
        "futureroots",
        cdk.SecretValue.unsafePlainText(dbPassword)
      ),
      multiAz: false,
      backupRetention: cdk.Duration.days(7),
      deletionProtection: false,
      removalPolicy: cdk.RemovalPolicy.SNAPSHOT,
    });

    // --- Media bucket: private, browser uploads via presigned URLs
    const mediaBucket = new s3.Bucket(this, "MediaBucket", {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      cors: [
        {
          allowedMethods: [s3.HttpMethods.PUT, s3.HttpMethods.GET],
          allowedOrigins: allOrigins,
          allowedHeaders: ["*"],
          maxAge: 3600,
        },
      ],
    });

    // --- API Lambda
    const apiSecurityGroup = new ec2.SecurityGroup(this, "ApiSg", { vpc });
    dbSecurityGroup.addIngressRule(
      apiSecurityGroup,
      ec2.Port.tcp(5432),
      "API Lambda to Postgres"
    );

    const apiFn = new lambda.Function(this, "ApiFn", {
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.X86_64,
      handler: "app.lambda_handler.handler",
      code: lambda.Code.fromAsset(
        path.join(__dirname, "..", "..", "apps", "api", "build", "lambda.zip")
      ),
      memorySize: 512,
      timeout: cdk.Duration.seconds(30),
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [apiSecurityGroup],
      environment: {
        FUTUREROOTS_DATABASE_URL: `postgresql+psycopg://futureroots:${dbPassword}@${db.dbInstanceEndpointAddress}:5432/futureroots`,
        FUTUREROOTS_JWT_SECRET: jwtSecret,
        FUTUREROOTS_STORAGE_BACKEND: "s3",
        FUTUREROOTS_MEDIA_BUCKET: mediaBucket.bucketName,
        FUTUREROOTS_EMAIL_BACKEND: "ses",
        FUTUREROOTS_SES_FROM_ADDRESS: sesFrom,
        FUTUREROOTS_WEB_BASE_URL: webBaseUrl,
        FUTUREROOTS_CORS_EXTRA_ORIGINS: extraOrigins.join(","),
        FUTUREROOTS_PAYMENT_BACKEND: "stripe",
        FUTUREROOTS_STRIPE_SECRET_KEY: process.env.STRIPE_SECRET_KEY ?? "",
        FUTUREROOTS_STRIPE_WEBHOOK_SECRET: process.env.STRIPE_WEBHOOK_SECRET ?? "",
        // Second webhook secret: Connect events (account.updated) arrive on a
        // separate connected-accounts endpoint with its own signing secret.
        FUTUREROOTS_STRIPE_CONNECT_WEBHOOK_SECRET:
          process.env.STRIPE_CONNECT_WEBHOOK_SECRET ?? "",
        // FutureRoots Premium — Stripe Price ids (not secrets; amounts live in
        // Stripe). Empty ids keep Premium checkout dark (503), never broken.
        FUTUREROOTS_STRIPE_PRICE_MONTHLY: process.env.STRIPE_PRICE_MONTHLY ?? "",
        FUTUREROOTS_STRIPE_PRICE_ANNUAL: process.env.STRIPE_PRICE_ANNUAL ?? "",
        FUTUREROOTS_STRIPE_PRICE_GIFT_YEAR:
          process.env.STRIPE_PRICE_GIFT_YEAR ?? "",
        FUTUREROOTS_AGORA_APP_ID: "c58c8181f4204f07bc1a36d93cae5514",
        FUTUREROOTS_AGORA_APP_CERTIFICATE: agoraSecret,
      },
    });
    mediaBucket.grantReadWrite(apiFn);
    mediaBucket.grantPut(apiFn);
    apiFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["ses:SendEmail"],
        resources: ["*"],
      })
    );

    // --- HTTP API
    const httpApi = new apigwv2.HttpApi(this, "HttpApi", {
      apiName: "futureroots-api",
      defaultIntegration: new HttpLambdaIntegration("ApiIntegration", apiFn),
    });

    // --- Testnet harness: same code, separate database + simulated payments.
    // The gamified tester surface at testnet.futureroots.app talks to this
    // Lambda only; the family product never sees testnet mode.
    const testnetFn = new lambda.Function(this, "TestnetApiFn", {
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.X86_64,
      handler: "app.lambda_handler.handler",
      code: lambda.Code.fromAsset(
        path.join(__dirname, "..", "..", "apps", "api", "build", "lambda.zip")
      ),
      memorySize: 512,
      timeout: cdk.Duration.seconds(30),
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [apiSecurityGroup],
      environment: {
        FUTUREROOTS_DATABASE_URL: `postgresql+psycopg://futureroots:${dbPassword}@${db.dbInstanceEndpointAddress}:5432/futureroots_testnet`,
        FUTUREROOTS_JWT_SECRET: jwtSecret,
        FUTUREROOTS_STORAGE_BACKEND: "s3",
        FUTUREROOTS_MEDIA_BUCKET: mediaBucket.bucketName,
        FUTUREROOTS_EMAIL_BACKEND: "ses",
        FUTUREROOTS_SES_FROM_ADDRESS: sesFrom,
        FUTUREROOTS_WEB_BASE_URL: testnetWebUrl,
        FUTUREROOTS_CORS_EXTRA_ORIGINS: "http://localhost:3000",
        FUTUREROOTS_PAYMENT_BACKEND: "local",
        FUTUREROOTS_TESTNET_MODE: "1",
        FUTUREROOTS_TESTNET_ADMIN_TOKEN: process.env.TESTNET_ADMIN_TOKEN ?? "",
        FUTUREROOTS_X_CLIENT_ID: process.env.X_CLIENT_ID ?? "",
        FUTUREROOTS_X_CLIENT_SECRET: process.env.X_CLIENT_SECRET ?? "",
        FUTUREROOTS_AGORA_APP_ID: "c58c8181f4204f07bc1a36d93cae5514",
        FUTUREROOTS_AGORA_APP_CERTIFICATE: agoraSecret,
      },
    });
    mediaBucket.grantReadWrite(testnetFn);
    testnetFn.addToRolePolicy(
      new iam.PolicyStatement({ actions: ["ses:SendEmail"], resources: ["*"] })
    );
    const testnetApi = new apigwv2.HttpApi(this, "TestnetHttpApi", {
      apiName: "futureroots-testnet-api",
      defaultIntegration: new HttpLambdaIntegration("TestnetApiIntegration", testnetFn),
    });
    new cdk.CfnOutput(this, "TestnetApiUrl", { value: testnetApi.apiEndpoint });
    new cdk.CfnOutput(this, "TestnetApiFunctionName", { value: testnetFn.functionName });

    new cdk.CfnOutput(this, "ApiUrl", { value: httpApi.apiEndpoint });
    new cdk.CfnOutput(this, "MediaBucketName", { value: mediaBucket.bucketName });
    new cdk.CfnOutput(this, "DbEndpoint", { value: db.dbInstanceEndpointAddress });
    new cdk.CfnOutput(this, "ApiFunctionName", { value: apiFn.functionName });
  }
}
