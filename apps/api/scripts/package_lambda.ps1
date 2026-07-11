# Packages the API into build/lambda.zip for AWS Lambda (python3.13, x86_64).
# Cross-platform install: wheels only, targeting manylinux from Windows.
# Run from apps/api:  powershell -File scripts\package_lambda.ps1

$ErrorActionPreference = "Stop"
$uv = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\astral-sh.uv_*\uv.exe" | Select-Object -First 1 -ExpandProperty FullName
$apiRoot = Split-Path $PSScriptRoot -Parent
Set-Location $apiRoot

$stage = "build\stage"
if (Test-Path build) { Remove-Item -Recurse -Force build -Confirm:$false }
New-Item -ItemType Directory -Force $stage | Out-Null

# 1. Resolve locked deps (runtime + aws group, no dev) to a requirements file
& $uv export --frozen --no-dev --group aws --no-emit-project --no-hashes -o build\requirements.txt
if ($LASTEXITCODE -ne 0) { throw "uv export failed" }

# 2. Install Linux wheels into the stage dir
# Lambda python3.13 runs on AL2023 (glibc 2.34) -> manylinux_2_28 wheels are fine
& $uv pip install -r build\requirements.txt --target $stage `
    --python-platform x86_64-manylinux_2_28 --python-version 3.13 --only-binary :all:
if ($LASTEXITCODE -ne 0) { throw "uv pip install failed" }

# 3. Application code + migrations ("migrations" in the zip: the "alembic"
#    name collides with the installed alembic library package)
Copy-Item -Recurse app "$stage\app"
Copy-Item -Recurse alembic "$stage\migrations"
Get-ChildItem -Recurse $stage -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -Confirm:$false

# 4. Zip with forward slashes (Compress-Archive writes backslash entries that
#    break Lambda, so use Python's zipfile via a real Python)
$zipScript = @'
import os, sys, zipfile
stage, out = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for root, _, files in os.walk(stage):
        for f in files:
            full = os.path.join(root, f)
            z.write(full, os.path.relpath(full, stage).replace(os.sep, "/"))
print(out, os.path.getsize(out), "bytes")
'@
Set-Content -Encoding utf8 build\make_zip.py $zipScript
& $uv run python build\make_zip.py $stage build\lambda.zip
if ($LASTEXITCODE -ne 0) { throw "zip failed" }
Write-Output "Packaged build\lambda.zip"
