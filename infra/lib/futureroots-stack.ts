import * as path from "path";
import * as cdk from "aws-cdk-lib";
import * as apigwv2 from "aws-cdk-lib/aws-apigatewayv2";
import { HttpLambdaIntegration } from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as rds from "aws-cdk-lib/aws-rds";
import * as s3 from "aws-cdk-lib/aws-s3";
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

    // --- Network: two isolated AZs, no NAT (cost ceiling), endpoints for AWS services
    const vpc = new ec2.Vpc(this, "Vpc", {
      maxAzs: 2,
      natGateways: 0,
      subnetConfiguration: [
        { name: "app", subnetType: ec2.SubnetType.PRIVATE_ISOLATED, cidrMask: 24 },
      ],
    });
    vpc.addGatewayEndpoint("S3Endpoint", {
      service: ec2.GatewayVpcEndpointAwsService.S3,
    });
    // SES v2 API via PrivateLink so the VPC-bound Lambda can send email
    const sesEndpoint = vpc.addInterfaceEndpoint("SesEndpoint", {
      service: new ec2.InterfaceVpcEndpointAwsService("email"),
      privateDnsEnabled: true,
    });

    // --- Database: smallest real Postgres, never publicly reachable
    const dbSecurityGroup = new ec2.SecurityGroup(this, "DbSg", { vpc });
    const db = new rds.DatabaseInstance(this, "Db", {
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
          allowedOrigins: [...new Set([webBaseUrl, "http://localhost:3000"])],
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
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      securityGroups: [apiSecurityGroup],
      environment: {
        FUTUREROOTS_DATABASE_URL: `postgresql+psycopg://futureroots:${dbPassword}@${db.dbInstanceEndpointAddress}:5432/futureroots`,
        FUTUREROOTS_JWT_SECRET: jwtSecret,
        FUTUREROOTS_STORAGE_BACKEND: "s3",
        FUTUREROOTS_MEDIA_BUCKET: mediaBucket.bucketName,
        FUTUREROOTS_EMAIL_BACKEND: "ses",
        FUTUREROOTS_SES_FROM_ADDRESS: sesFrom,
        FUTUREROOTS_WEB_BASE_URL: webBaseUrl,
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
    sesEndpoint.connections.allowDefaultPortFrom(apiFn);

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
