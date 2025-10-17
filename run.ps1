# PowerShell script to run the application
# If you get execution policy errors, run: Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

Write-Host "Activating virtual environment..." -ForegroundColor Green
& .\venv\Scripts\Activate.ps1

Write-Host ""
Write-Host "Starting Projection BPP Listener Service..." -ForegroundColor Green
Write-Host ""

python run.py

Read-Host "Press Enter to exit"
