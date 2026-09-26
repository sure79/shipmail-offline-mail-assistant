@echo off
setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
echo ============================================================
echo  ShipMail 오프라인 점검
echo  먼저 와이파이를 끄거나 랜선을 뽑은 뒤 실행하세요.
echo  (내 데이터 data 폴더는 건드리지 않고 임시 DB로 점검합니다)
echo ============================================================
echo.
set "OLLAMA_EXE=ollama"
where ollama >nul 2>nul || set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
curl -s -m 3 http://127.0.0.1:11434/api/version >nul 2>nul
if errorlevel 1 (
  echo Ollama가 꺼져 있어 로컬 전용 모드로 켭니다...
  start "Ollama (local only)" /min cmd /c "set OLLAMA_HOST=127.0.0.1:11434&& set OLLAMA_NO_CLOUD=1&& set OLLAMA_MAX_LOADED_MODELS=1&& set OLLAMA_NUM_PARALLEL=1&& set OLLAMA_FLASH_ATTENTION=1&& set OLLAMA_KV_CACHE_TYPE=q8_0&& "%OLLAMA_EXE%" serve"
  timeout /t 8 /nobreak >nul
)
if exist "runtime\python.exe" ( "runtime\python.exe" offline_check.py ) else ( py -3 offline_check.py )
echo.
echo 점검이 끝났습니다. 인터넷을 다시 연결한 뒤 Claude에게 "점검 끝났어"라고 알려 주세요.
pause
