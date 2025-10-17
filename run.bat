@echo off
REM Activate virtual environment and run the application

echo Activating virtual environment...
call venv\Scripts\activate.bat

echo.
echo Starting Projection BPP Listener Service...
echo.

python run.py

pause
