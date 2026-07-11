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
    const webBaseUrl = process.env.WEB_BASE_URL ?? "http://localhost:3000";
    const extraOrigins = (process.env.EXTRA_ORIGINS ?? "")
      .split(",")
      .map((o) => o.trim())
      .filter(Boolean);
    const allOrigins = [...new Set([webBaseUrl, "http://localhost:3000", ...extraOrigins])];

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

    new cdk.CfnOutput(this, "ApiUrl", { value: httpApi.apiEndpoint });
    new cdk.CfnOutput(this, "MediaBucketName", { value: mediaBucket.bucketName });
    new cdk.CfnOutput(this, "DbEndpoint", { value: db.dbInstanceEndpointAddress });
    new cdk.CfnOutput(this, "ApiFunctionName", { value: apiFn.functionName });
  }
}
