# ShipMail one-shot setup for a new Windows PC (run inside the downloaded/cloned folder).
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
# Options:
#   -Model <name>      Ollama model to use (default qwen3:8b; qwen3:4b-instruct-2507-q4_K_M for 8GB RAM PCs)
#   -Restore <file>    Restore a ShipMail backup JSON (glossary / corrected examples) from another PC
#   -Yes               Answer "yes" to download questions (Ollama installer, model)
#   -NoShortcut        Do not create the desktop shortcut
# Downloads happen ONLY after confirmation: the Ollama installer (official GitHub release, SHA256 verified) and the model.
# Business mail never leaves the PC: the app and Ollama listen on 127.0.0.1 only and Ollama cloud features are disabled.
param(
  [string]$Model = 'qwen3:8b',
  [string]$Restore = '',
  [switch]$Yes,
  [switch]$NoShortcut
)
$ErrorActionPreference = 'Stop'
$App = $PSScriptRoot
$results = New-Object System.Collections.Generic.List[string]
function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "   [OK] $msg" -ForegroundColor Green; $results.Add("[OK] $msg") }
function Warn($msg) { Write-Host "   [확인 필요] $msg" -ForegroundColor Yellow; $results.Add("[확인 필요] $msg") }
function Ask($q) { if ($Yes) { return $true }; return ((Read-Host "$q (Y/N)") -match '^[yY]') }

# 1. Python
Step '1. Python 3.11 이상 확인'
$py = $null
foreach ($cand in @(@('py','-3'), @('python'))) {
  try {
    $v = & $cand[0] $cand[1..($cand.Length-1)] -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
    if ($LASTEXITCODE -eq 0 -and $v -match '^3\.(\d+)$' -and [int]$Matches[1] -ge 11) { $py = $cand; Ok "Python $v"; break }
  } catch {}
}
if (-not $py) {
  Warn 'Python 3.11 이상이 없습니다. https://www.python.org/downloads/windows/ 에서 설치("Add python.exe to PATH" 체크) 후 다시 실행하세요.'
  exit 1
}
function RunPy([string[]]$argsList) { & $py[0] @($py[1..($py.Length-1)] + $argsList) }

# 2. Ollama
Step '2. 로컬 AI 엔진(Ollama)'
$ollamaExe = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
if (-not (Test-Path $ollamaExe)) { $cmd = Get-Command ollama -ErrorAction SilentlyContinue; if ($cmd) { $ollamaExe = $cmd.Source } }
if (Test-Path $ollamaExe) { Ok "Ollama 설치됨: $ollamaExe" }
elseif (Ask 'Ollama가 없습니다. 공식 GitHub 릴리스에서 설치 파일(약 1.5GB)을 받아 설치할까요?') {
  $rel = Invoke-RestMethod 'https://api.github.com/repos/ollama/ollama/releases/latest' -Headers @{ 'User-Agent' = 'shipmail-setup' }
  $asset = $rel.assets | Where-Object { $_.name -eq 'OllamaSetup.exe' } | Select-Object -First 1
  if (-not $asset) { Warn 'OllamaSetup.exe 를 릴리스에서 찾지 못했습니다. https://ollama.com/download 에서 직접 설치하세요.'; exit 1 }
  $installer = Join-Path $env:TEMP 'OllamaSetup.exe'
  Write-Host "   다운로드: $($rel.tag_name) ($([math]::Round($asset.size/1GB,2))GB) ..."
  $ProgressPreference = 'SilentlyContinue'
  Invoke-WebRequest $asset.browser_download_url -OutFile $installer -UseBasicParsing
  $hash = (Get-FileHash $installer -Algorithm SHA256).Hash.ToLower()
  if ($asset.digest -and ($asset.digest -replace '^sha256:', '') -ne $hash) { Remove-Item $installer; Warn 'SHA256 불일치 — 설치를 중단했습니다.'; exit 1 }
  Ok "설치 파일 SHA256 확인: $hash"
  Start-Process $installer -ArgumentList '/VERYSILENT','/NORESTART','/SUPPRESSMSGBOXES' -Wait
  Remove-Item $installer -ErrorAction SilentlyContinue
  $ollamaExe = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
  if (Test-Path $ollamaExe) { Ok "Ollama $($rel.tag_name) 설치 완료 (로그인·회원가입 불필요)" } else { Warn 'Ollama 설치를 확인하지 못했습니다.'; exit 1 }
} else { Warn 'Ollama 미설치 — https://ollama.com/download 에서 설치 후 다시 실행하세요.'; exit 1 }

# 3. Cloud features off
Step '3. Ollama 클라우드 기능 끄기'
$ollamaDir = Join-Path $env:USERPROFILE '.ollama'
New-Item -ItemType Directory -Force $ollamaDir | Out-Null
$cfgPath = Join-Path $ollamaDir 'server.json'
$cfg = @{}
if (Test-Path $cfgPath) { try { (Get-Content $cfgPath -Raw | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $cfg[$_.Name] = $_.Value } } catch {} }
$cfg['disable_ollama_cloud'] = $true
[IO.File]::WriteAllText($cfgPath, ($cfg | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))
Ok "$cfgPath : disable_ollama_cloud = true"

# 4. Start Ollama (local only) and get the model
Step "4. AI 모델 준비: $Model"
function OllamaUp { try { Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 3 | Out-Null; $true } catch { $false } }
if (-not (OllamaUp)) {
  # The tray app may start after install; stop it so our local-only server owns the port.
  Get-Process 'ollama app' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  $env:OLLAMA_HOST = '127.0.0.1:11434'; $env:OLLAMA_NO_CLOUD = '1'; $env:OLLAMA_FLASH_ATTENTION = '1'; $env:OLLAMA_KV_CACHE_TYPE = 'q8_0'
  $env:OLLAMA_MAX_LOADED_MODELS = '1'; $env:OLLAMA_NUM_PARALLEL = '1'
  Start-Process $ollamaExe -ArgumentList 'serve' -WindowStyle Minimized
  for ($i = 0; $i -lt 20 -and -not (OllamaUp); $i++) { Start-Sleep 1 }
}
if (-not (OllamaUp)) { Warn 'Ollama 서버를 켜지 못했습니다. start-ollama-local.bat 을 실행해 보세요.'; exit 1 }
$names = @((Invoke-RestMethod 'http://127.0.0.1:11434/api/tags').models | ForEach-Object { $_.name })
if ($names -contains $Model) { Ok "모델 설치됨: $Model" }
elseif (Ask "모델 $Model 을(를) 받을까요? (qwen3:8b 약 5.2GB / qwen3:4b-instruct-2507-q4_K_M 약 2.5GB)") {
  & $ollamaExe pull $Model
  $names = @((Invoke-RestMethod 'http://127.0.0.1:11434/api/tags').models | ForEach-Object { $_.name })
  if ($names -contains $Model) { Ok "모델 다운로드 완료: $Model" } else { Warn "모델 다운로드 실패: $Model"; exit 1 }
} else { Warn "모델 $Model 미설치 — 나중에: ollama pull $Model" }

# 5. App data: settings (+ optional restore)
Step '5. 앱 설정'
$env:PYTHONIOENCODING = 'utf-8'
$cfgPy = Join-Path $env:TEMP 'shipmail_setup.py'
@"
import json, sys
sys.path.insert(0, r'$App')
from store import Store
from model import validate_settings
db = Store(r'$App\data\shipmail.sqlite3')
restore = r'''$Restore'''
if restore:
    snap = json.load(open(restore, encoding='utf-8-sig'))
    print('restore-backup', db.restore(snap, validate_settings))
settings = db.settings({'model': r'$Model', 'timeout': max(db.settings()['timeout'], 600)})
terms = db.list('terms'); ex = db.list('examples')
print('model=%s terms=%d(reviewed %d) examples=%d(reviewed %d)' % (settings['model'], len(terms), sum(t.get('status') == 'reviewed' for t in terms), len(ex), sum(e.get('status') == 'reviewed' for e in ex)))
"@ | Set-Content -Path $cfgPy -Encoding UTF8
$out = RunPy @($cfgPy)
Remove-Item $cfgPy -ErrorAction SilentlyContinue
if ($LASTEXITCODE -eq 0) { Ok ($out -join ' ') } else { Warn "설정 실패: $out" }

# 6. Tests
Step '6. 자동 테스트'
Push-Location $App
$ErrorActionPreference = 'Continue'   # unittest reports on stderr
$testOut = RunPy @('-m','unittest','discover','-s','tests') 2>&1 | ForEach-Object { "$_" } | Out-String
$ErrorActionPreference = 'Stop'
Pop-Location
$ran = [regex]::Match($testOut, 'Ran (\d+) tests').Groups[1].Value
if ($testOut -match '(?m)^OK') { Ok "테스트 $ran 개 통과" } else { Warn "테스트 실패:`n$testOut" }

# 7. Shortcut
if (-not $NoShortcut) {
  Step '7. 바탕화면 바로가기'
  $lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'ShipMail.lnk'
  $s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
  $s.TargetPath = Join-Path $App 'start-all.bat'; $s.WorkingDirectory = $App
  $s.Description = 'ShipMail - 오프라인 영어메일 도우미'; $s.Save()
  Ok "바로가기: $lnk"
}

Write-Host "`n================ 요약 ================" -ForegroundColor Cyan
$results | ForEach-Object { Write-Host $_ }
Write-Host "실행: 바탕화면 ShipMail 아이콘 (또는 $App\start-all.bat)"
