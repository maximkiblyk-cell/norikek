@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (echo Create .venv and install dependencies: see README.md & pause & exit /b 1)
if not exist ".env" (echo Create and configure .env: see README.md & pause & exit /b 1)
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
