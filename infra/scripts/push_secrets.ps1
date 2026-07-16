# push_secrets.ps1 - create/update the consolidated FutureRoots API secret.
#
# Reads secret values from infra/.env (gitignored) and pushes them as ONE
# Secrets Manager secret (`futureroots/api`) whose SecretString is a JSON
# object keyed by env-var name. The CDK stack imports this secret by name and
# the API loads it at Lambda cold start (apps/api/app/config.py overlay) -
# the values never appear in the CloudFormation template or Lambda env vars.
#
# Database credentials are NOT in this secret: the RDS master password is
# generated and rotated by RDS itself (manageMasterUserPassword in the CDK
# stack) in its own managed secret (name pattern rds!db-...), and the app
# composes the database URL from that secret plus FUTUREROOTS_DB_HOST.
# DB_PASSWORD in infra/.env is obsolete and ignored here.
#
# Idempotent: creates the secret if absent, otherwise puts a new version.
# Never prints secret values. Run BEFORE `cdk deploy` whenever .env changes:
#
#   powershell -ExecutionPolicy Bypass -File scripts\push_secrets.ps1

param(
    [string]$SecretName = "futureroots/api",
    [string]$Region = "us-east-1"
)

$ErrorActionPreference = "Stop"

# --- Parse infra/.env (KEY=VALUE lines; first '=' splits; no quoting rules)
$envFile = Join-Path $PSScriptRoot "..\.env"
if (-not (Test-Path $envFile)) { throw "Not found: $envFile (infra/.env holds the secret values)" }
$envVars = @{}
foreach ($line in Get-Content $envFile) {
    if ($line -match '^([A-Z_]+)=(.*)$') { $envVars[$Matches[1]] = $Matches[2] }
}

function Get-Required([string]$name) {
    if (-not $envVars[$name]) { throw "Missing required $name in infra/.env" }
    return $envVars[$name]
}
function Get-Optional([string]$name) {
    if (-not $envVars[$name]) {
        Write-Warning "$name is empty/absent in infra/.env - pushing empty string (feature stays dark)"
        return ""
    }
    return $envVars[$name]
}

# --- Build the JSON blob (keys = the env-var names the API expects).
$payload = [ordered]@{
    FUTUREROOTS_JWT_SECRET                    = (Get-Required "JWT_SECRET")
    FUTUREROOTS_STRIPE_SECRET_KEY             = (Get-Optional "STRIPE_SECRET_KEY")
    FUTUREROOTS_STRIPE_WEBHOOK_SECRET         = (Get-Optional "STRIPE_WEBHOOK_SECRET")
    FUTUREROOTS_STRIPE_CONNECT_WEBHOOK_SECRET = (Get-Optional "STRIPE_CONNECT_WEBHOOK_SECRET")
    FUTUREROOTS_AGORA_APP_CERTIFICATE         = (Get-Required "AGORA_SECRET")
    # Testnet-harness secrets (inert on the main API Lambda: testnet_mode off).
    FUTUREROOTS_TESTNET_ADMIN_TOKEN           = (Get-Optional "TESTNET_ADMIN_TOKEN")
    FUTUREROOTS_X_CLIENT_SECRET               = (Get-Optional "X_CLIENT_SECRET")
}
$json = $payload | ConvertTo-Json -Compress

# --- Does the secret exist yet? (describe-secret exit code; stderr suppressed)
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
aws secretsmanager describe-secret --secret-id $SecretName --region $Region --output json 2>$null | Out-Null
$exists = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $prevEap

# --- Push. The JSON goes via a transient temp file (file://) so the values
# never sit on a process command line; the file is deleted in `finally`.
$tmp = Join-Path $env:TEMP ("fr-secret-" + [guid]::NewGuid().ToString("N") + ".json")
try {
    [System.IO.File]::WriteAllText($tmp, $json, [System.Text.UTF8Encoding]::new($false))
    if ($exists) {
        aws secretsmanager put-secret-value --secret-id $SecretName --region $Region `
            --secret-string "file://$tmp" --output json | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "put-secret-value failed for '$SecretName'" }
        Write-Host "Updated secret '$SecretName' ($($payload.Count) keys) in $Region"
    } else {
        aws secretsmanager create-secret --name $SecretName --region $Region `
            --description "FutureRoots API runtime secrets (consolidated JSON; loaded by app/config.py at Lambda cold start)" `
            --secret-string "file://$tmp" --output json | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "create-secret failed for '$SecretName'" }
        Write-Host "Created secret '$SecretName' ($($payload.Count) keys) in $Region"
    }
} finally {
    if (Test-Path $tmp) { Remove-Item -Force $tmp }
}
