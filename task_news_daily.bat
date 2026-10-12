@echo off
cd /d "%~dp0"
"%~dp0venv32\Scripts\python.exe" news_daily.py --days 14
