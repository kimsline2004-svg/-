@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Diagnostics
echo == Python ==
python --version
echo.
echo == Import check ==
python -c "import streamlit, altair, pandas, requests; print('imports OK')"
echo.
echo == app.py syntax check ==
python -m py_compile app.py && echo syntax OK
echo.
echo == Installed packages ==
python -m pip list
echo.
pause
