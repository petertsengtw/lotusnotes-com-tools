@echo off
cd /d "%~dp0store"
"%~dp0venv32\Scripts\python.exe" expiry_report.py --notify >> "%~dp0store\output\expiry_report.log" 2>&1
