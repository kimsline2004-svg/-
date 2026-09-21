@echo off
chcp 65001 >nul
cd /d "%~dp0"
title US Stock Financials Viewer

python --version >nul 2>&1
if errorlevel 1 (
  echo.
  echo  Python is not installed, or it is not on PATH.
  echo  Install from https://www.python.org/downloads/
  echo  and tick "Add python.exe to PATH" on the first setup screen.
  echo.
  pause
  exit /b
)

python -c "import streamlit, altair" >nul 2>&1
if errorlevel 1 (
  echo.
  echo  Installing required packages. The first run takes a few minutes...
  echo.
  python -m pip install -r requirements.txt
)

echo.
echo  Starting app...  http://localhost:8510
echo  Press Ctrl+C to stop. Do NOT click inside this window.
echo.
python -m streamlit run app.py --server.port 8510
pause
