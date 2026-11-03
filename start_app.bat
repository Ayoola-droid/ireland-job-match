@echo off
REM Double-click this file to open Ireland Job Match in your web browser.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m streamlit run app.py
pause
