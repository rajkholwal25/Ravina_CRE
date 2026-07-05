@echo off
REM Double-click to launch the Dialysis Handbook Quiz app.
cd /d "%~dp0"
echo Installing Flask (first run only)...
python -m pip install --quiet flask
echo Starting quiz server...
start "" http://127.0.0.1:5000
python app.py
pause
