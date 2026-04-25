@echo off
echo Starting LeadGen AI...
echo.
cd /d "%~dp0backend"
start "" "http://localhost:8000"
"C:\Users\Varuni Singh\AppData\Local\Programs\Python\Python310\python.exe" -m uvicorn main:app --reload --port 8000
pause
