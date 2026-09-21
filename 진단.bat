@echo off
cd /d "%~dp0"
title 진단 - 미국주식 재무 조회기

set PYEXE=
python -c "import sys" >nul 2>&1 && set PYEXE=python
if not defined PYEXE (
  py -3 -c "import sys" >nul 2>&1 && set PYEXE=py -3
)
if not defined PYEXE (
  echo  [오류] 파이썬을 찾지 못했습니다. PATH 등록 여부를 확인하세요.
  pause
  exit /b 1
)

echo == 현재 폴더 ==
echo %CD%
echo.
echo == 폴더 내용 ==
dir /b
echo.
echo == 파이썬 ==
echo %PYEXE%
%PYEXE% --version
echo.
echo == import 확인 ==
%PYEXE% -c "import streamlit, altair, pandas, requests; print('imports OK')"
echo.
echo == app.py 문법 확인 ==
%PYEXE% -m py_compile app.py && echo syntax OK
echo.
echo == 설치된 패키지 ==
%PYEXE% -m pip list
echo.
echo  위 내용을 복사해서 알려주세요.
pause
