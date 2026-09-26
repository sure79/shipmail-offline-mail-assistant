# Builds dist\ShipMail-<version>.zip WITHOUT data/, backups, eval results or model files.
# Optional: put a Windows embeddable Python in .\runtime (python.exe) before running to make a portable package.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$version = '1.1'
$stage = Join-Path $env:TEMP "shipmail-pkg-$([guid]::NewGuid())"
New-Item -ItemType Directory $stage | Out-Null
$items = 'app.py','model.py','store.py','checks.py','seed.py','evaluate.py','offline_check.py','offline-check.bat','static','evals\cases.json','evals\realistic.json','tests\test_app.py',
         'start.bat','start-all.bat','start-ollama-local.bat','evaluate.bat','run-tests.bat','README.md','docs','requirements.txt','AGENTS.md','CLAUDE.md'
foreach ($i in $items) {
  $dest = Join-Path $stage $i
  New-Item -ItemType Directory -Force (Split-Path $dest) | Out-Null
  Copy-Item -Recurse $i $dest
}
if (Test-Path runtime\python.exe) { Copy-Item -Recurse runtime (Join-Path $stage 'runtime') }
New-Item -ItemType Directory -Force dist | Out-Null
$zip = "dist\ShipMail-$version.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "$stage\*" -DestinationPath $zip
Remove-Item -Recurse -Force $stage
Get-FileHash -Algorithm SHA256 $zip | Format-List
Write-Host "패키지: $zip  (모델 파일은 포함하지 않습니다)"
