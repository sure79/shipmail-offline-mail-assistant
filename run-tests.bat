@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if exist "runtime\python.exe" ( "runtime\python.exe" -m unittest discover -s tests -v ) else ( py -3 -m unittest discover -s tests -v )
pause
