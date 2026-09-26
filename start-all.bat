@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
rem ShipMail one-click start: local-only Ollama (if not already running) + app. No downloads.
set "OLLAMA_EXE=ollama"
where ollama >nul 2>nul || set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
curl -s -m 3 http://127.0.0.1:11434/api/version >nul 2>nul
if errorlevel 1 (
  if not exist "%OLLAMA_EXE%" if not "%OLLAMA_EXE%"=="ollama" (
    echo [ShipMail] Ollama가 설치되어 있지 않습니다. CLAUDE_CODE_SETUP.md 를 참고하세요.
    pause
    exit /b 1
  )
  echo [ShipMail] 로컬 AI 엔진을 켜는 중입니다... (이 PC 안에서만 동작)
  start "Ollama (local only)" /min cmd /c "set OLLAMA_HOST=127.0.0.1:11434&& set OLLAMA_NO_CLOUD=1&& set OLLAMA_MAX_LOADED_MODELS=1&& set OLLAMA_NUM_PARALLEL=1&& set OLLAMA_FLASH_ATTENTION=1&& set OLLAMA_KV_CACHE_TYPE=q8_0&& "%OLLAMA_EXE%" serve"
  timeout /t 6 /nobreak >nul
)
call "%~dp0start.bat"
