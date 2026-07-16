#!/usr/bin/env node
import * as fs from "fs";
import * as path from "path";
import * as cdk from "aws-cdk-lib";
import { FutureRootsStack } from "../lib/futureroots-stack";

// Load infra/.env (gitignored) — SES_FROM_ADDRESS, WEB_BASE_URL, Stripe price ids
// (the RDS master password is managed by RDS/Secrets Manager; app secrets are
// pushed out-of-band by scripts/push_secrets.ps1 — neither is read here)
const envFile = path.join(__dirname, "..", ".env");
if (fs.existsSync(envFile)) {
  for (const line of fs.readFileSync(envFile, "utf-8").split(/\r?\n/)) {
    const m = line.match(/^([A-Z_]+)=(.*)$/);
    if (m && !process.env[m[1]]) process.env[m[1]] = m[2];
  }
}

const app = new cdk.App();
new FutureRootsStack(app, "FutureRoots", {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION ?? "us-east-1",
  },
});
