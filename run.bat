@echo off
python "%~dp0compressor.py"
if %errorlevel% neq 0 pause
