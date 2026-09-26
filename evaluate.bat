@echo off
setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
rem 사용 예: evaluate.bat --model qwen3:4b-instruct-2507-q4_K_M
if exist "runtime\python.exe" ( "runtime\python.exe" evaluate.py %* ) else ( py -3 evaluate.py %* )
pause
