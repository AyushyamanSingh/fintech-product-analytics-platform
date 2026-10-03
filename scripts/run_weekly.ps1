# Weekly pipeline run for Windows Task Scheduler (synthetic data).
#
# Register once (runs every Monday 07:00 local time):
#   schtasks /Create /SC WEEKLY /D MON /ST 07:00 /TN "FinTechAnalyticsWeekly" `
#     /TR "powershell -NoProfile -ExecutionPolicy Bypass -File \"<repo>\scripts\run_weekly.ps1\""
#
# Exit code is non-zero when a step or the data-quality gate fails, so Task Scheduler history shows failures.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Virtual environment not found - run: python -m venv .venv; .venv\Scripts\pip install -r requirements.txt" }
& $python pipeline.py --generate
exit $LASTEXITCODE
