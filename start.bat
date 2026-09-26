@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
rem ShipMail: runs only on this PC (127.0.0.1). No internet install/update at startup.
if exist "runtime\python.exe" (
  "runtime\python.exe" app.py
  goto done
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 app.py
) else (
  python app.py
)
if errorlevel 1 (
  echo.
  echo [ShipMail] 실행 실패. 승인된 Python 3.11 이상을 설치하거나 runtime 폴더가 포함된 휴대용 패키지를 사용하세요.
  echo 포트 8765가 사용 중이면 다른 ShipMail 창을 먼저 닫으세요.
)
:done
pause
