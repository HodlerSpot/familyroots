import * as path from "path";
import * as cdk from "aws-cdk-lib";
import * as apigwv2 from "aws-cdk-lib/aws-apigatewayv2";
import { HttpLambdaIntegration } from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as events from "aws-cdk-lib/aws-events";
import * as targets from "aws-cdk-lib/aws-events-targets";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as rds from "aws-cdk-lib/aws-rds";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
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

    // No secret values are read here at all: the RDS master password is
    // generated and stored by RDS itself (manageMasterUserPassword below),
    // and the app-level runtime secrets (JWT, Stripe keys, Agora certificate)
    // live in the consolidated Secrets Manager secret `futureroots/api`,
    // pushed out-of-band by infra/scripts/push_secrets.ps1 — they are
    // deliberately NOT read into Lambda env vars (plaintext in the CFN
    // template) anymore.
    const sesFrom = required("SES_FROM_ADDRESS");
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
      // RDS generates the master password and manages it in a Secrets Manager
      // secret it owns (name pattern `rds!db-...`) — no password in infra/.env
      // or the CFN template. Switching an existing instance from an inline
      // MasterUserPassword to ManageMasterUserPassword is an in-place update:
      // RDS mints a fresh password during the deploy (the old one dies).
      credentials: rds.Credentials.fromUsername("futureroots"),
      manageMasterUserPassword: true,
      multiAz: false,
      backupRetention: cdk.Duration.days(7),
      // Real families are aboard: the instance must survive both an explicit
      // delete attempt (deletionProtection) and a stack teardown (RETAIN).
      deletionProtection: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });
    // The RDS-managed master-user secret. `db.secret` resolves through the
    // instance's `MasterUserSecret.Secret.Arn` attribute, so every reference
    // below (Lambda env, IAM grants) carries an implicit CloudFormation
    // dependency on the RDS update: on the cutover deploy the instance
    // switches to the managed password FIRST, and only then does the Lambda
    // configuration start pointing at the secret.
    const dbMasterSecret = db.secret;
    if (!dbMasterSecret) {
      throw new Error(
        "RDS instance exposes no managed master-user secret — manageMasterUserPassword must stay enabled"
      );
    }

    // --- Secrets: ONE consolidated secret (JSON blob keyed by env-var name),
    // created/populated OUT-OF-BAND via infra/scripts/push_secrets.ps1 so the
    // values never enter the CloudFormation template. Imported by name here;
    // the API reads it once per cold start (app/config.py overlay) via the
    // NAT instance — no VPC endpoint needed (and none added: it costs money).
    const apiSecrets = secretsmanager.Secret.fromSecretNameV2(
      this,
      "ApiSecrets",
      "futureroots/api"
    );

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
        // Sensitive values (_JWT_SECRET, the Stripe secrets,
        // _AGORA_APP_CERTIFICATE) are NOT set here — the app fetches them
        // from the consolidated secret at cold start (app/config.py).
        FUTUREROOTS_SECRETS_ARN: apiSecrets.secretArn,
        // Database credentials: the RDS-managed master-user secret plus the
        // plain (non-secret) endpoint hostname. app/config.py composes the
        // SQLAlchemy URL at cold start; app/db.py re-fetches the secret and
        // retries once when a NEW connection hits an auth failure after a
        // password rotation, so rotations need no forced cold starts.
        FUTUREROOTS_DB_SECRET_ARN: dbMasterSecret.secretArn,
        FUTUREROOTS_DB_HOST: db.dbInstanceEndpointAddress,
        FUTUREROOTS_STORAGE_BACKEND: "s3",
        FUTUREROOTS_MEDIA_BUCKET: mediaBucket.bucketName,
        FUTUREROOTS_EMAIL_BACKEND: "ses",
        FUTUREROOTS_SES_FROM_ADDRESS: sesFrom,
        FUTUREROOTS_WEB_BASE_URL: webBaseUrl,
        FUTUREROOTS_CORS_EXTRA_ORIGINS: extraOrigins.join(","),
        FUTUREROOTS_PAYMENT_BACKEND: "stripe",
        // FutureRoots Premium — Stripe Price ids (not secrets; amounts live in
        // Stripe). Empty ids keep Premium checkout dark (503), never broken.
        FUTUREROOTS_STRIPE_PRICE_MONTHLY: process.env.STRIPE_PRICE_MONTHLY ?? "",
        FUTUREROOTS_STRIPE_PRICE_ANNUAL: process.env.STRIPE_PRICE_ANNUAL ?? "",
        FUTUREROOTS_STRIPE_PRICE_GIFT_YEAR:
          process.env.STRIPE_PRICE_GIFT_YEAR ?? "",
        // Public app id (shipped to clients); the certificate is in the secret.
        FUTUREROOTS_AGORA_APP_ID: "c58c8181f4204f07bc1a36d93cae5514",
        // Web Push (VAPID). Public key + subject are NOT secret — they ship to
        // browsers (served via GET /me/notifications, so no Amplify rebuild).
        // The private key lives in the futureroots/api secret blob
        // (push_secrets.ps1). Empty public key ?? "" keeps push dark by default.
        FUTUREROOTS_VAPID_PUBLIC_KEY: process.env.VAPID_PUBLIC_KEY ?? "",
        FUTUREROOTS_VAPID_SUBJECT:
          process.env.VAPID_SUBJECT ?? "mailto:hello@futureroots.app",
      },
    });
    apiSecrets.grantRead(apiFn);
    dbMasterSecret.grantRead(apiFn);
    mediaBucket.grantReadWrite(apiFn);
    mediaBucket.grantPut(apiFn);
    apiFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["ses:SendEmail"],
        resources: ["*"],
      })
    );

    // --- Daily maintenance: EventBridge invokes the API Lambda's management
    // entrypoint (app/lambda_handler.py dispatches on `futureroots_command`)
    // for scheduled sweeps (gift-intent prune, email-log retention, ...).
    // 09:00 UTC — early morning US, before family traffic picks up.
    const maintenanceRule = new events.Rule(this, "DailyMaintenanceRule", {
      description: "FutureRoots daily maintenance sweep (API Lambda management command)",
      schedule: events.Schedule.cron({ minute: "0", hour: "9" }),
    });
    maintenanceRule.addTarget(
      new targets.LambdaFunction(apiFn, {
        event: events.RuleTargetInput.fromObject({
          futureroots_command: "maintenance",
        }),
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
        // Same consolidated secret and same RDS-managed DB secret as the main
        // API. With FUTUREROOTS_TESTNET_MODE=1 the config overlay composes the
        // database URL against the `futureroots_testnet` database (separate
        // database, same server, same master user).
        FUTUREROOTS_SECRETS_ARN: apiSecrets.secretArn,
        FUTUREROOTS_DB_SECRET_ARN: dbMasterSecret.secretArn,
        FUTUREROOTS_DB_HOST: db.dbInstanceEndpointAddress,
        FUTUREROOTS_STORAGE_BACKEND: "s3",
        FUTUREROOTS_MEDIA_BUCKET: mediaBucket.bucketName,
        FUTUREROOTS_EMAIL_BACKEND: "ses",
        FUTUREROOTS_SES_FROM_ADDRESS: sesFrom,
        FUTUREROOTS_WEB_BASE_URL: testnetWebUrl,
        FUTUREROOTS_CORS_EXTRA_ORIGINS: "http://localhost:3000",
        FUTUREROOTS_PAYMENT_BACKEND: "local",
        FUTUREROOTS_TESTNET_MODE: "1",
        // Testnet-only secrets (admin token, X OAuth secret) also live in the
        // blob; only the public X client id stays as a plain env var.
        FUTUREROOTS_X_CLIENT_ID: process.env.X_CLIENT_ID ?? "",
        FUTUREROOTS_AGORA_APP_ID: "c58c8181f4204f07bc1a36d93cae5514",
      },
    });
    apiSecrets.grantRead(testnetFn);
    dbMasterSecret.grantRead(testnetFn);
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
