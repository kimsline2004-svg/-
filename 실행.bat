@echo off
cd /d "%~dp0"
title 미국주식 재무 조회기

rem ---- 파이썬 찾기: python -> py 순서 ----
set PYEXE=
python -c "import sys" >nul 2>&1 && set PYEXE=python
if not defined PYEXE (
  py -3 -c "import sys" >nul 2>&1 && set PYEXE=py -3
)
if not defined PYEXE (
  echo.
  echo  [오류] 파이썬을 찾지 못했습니다.
  echo.
  echo  https://www.python.org/downloads/ 에서 설치하고,
  echo  설치 첫 화면의 "Add python.exe to PATH" 를 반드시 체크하세요.
  echo  설치를 끝낸 뒤 이 창을 닫고 다시 실행하세요.
  echo.
  pause
  exit /b 1
)

rem ---- app.py 확인 ----
if not exist "app.py" (
  echo.
  echo  [오류] 이 폴더에 app.py 가 없습니다.
  echo  현재 폴더: %CD%
  echo.
  pause
  exit /b 1
)

echo  파이썬: %PYEXE%
%PYEXE% --version
echo.

rem ---- 필요한 패키지 확인 ----
%PYEXE% -c "import streamlit, altair, pandas, requests" >nul 2>&1
if errorlevel 1 (
  echo  필요한 패키지를 설치합니다. 처음 한 번은 몇 분 걸립니다...
  echo.
  %PYEXE% -m pip install -r requirements.txt
  %PYEXE% -c "import altair" >nul 2>&1 || %PYEXE% -m pip install altair
  echo.
)

%PYEXE% -c "import streamlit, altair, pandas, requests" >nul 2>&1
if errorlevel 1 (
  echo.
  echo  [오류] 패키지 설치에 실패했습니다. 위에 나온 메시지를 확인하세요.
  echo.
  pause
  exit /b 1
)

echo.
echo  앱을 시작합니다...  http://localhost:8510
echo  종료하려면 Ctrl+C 를 누르세요.
echo  이 창을 닫거나 창 안을 마우스로 클릭하지 마세요.
echo  (실수로 클릭해 멈췄다면 창을 클릭하고 Esc 를 누르면 다시 움직입니다.)
echo.
%PYEXE% -m streamlit run app.py --server.port 8510

echo.
echo  앱이 종료되었습니다.
pause
