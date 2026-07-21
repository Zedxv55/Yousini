@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
set "AGENT_DIR=%~dp0"
if "%AGENT_DIR:~-1%"=="\" set "AGENT_DIR=%AGENT_DIR:~0,-1%"
cd /d "%AGENT_DIR%"

set "PY="
where py >nul 2>&1
if %ERRORLEVEL%==0 (
  py -3 -c "import sys; raise SystemExit(0)" >nul 2>&1
  if !ERRORLEVEL!==0 set "PY=py -3"
)
if not defined PY (
  if defined LOCALAPPDATA (
    for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
      if exist "%%d\python.exe" (
        "%%d\python.exe" -c "import sys; raise SystemExit(0)" >nul 2>&1
        if !ERRORLEVEL!==0 set "PY=%%d\python.exe"
      )
    )
  )
)
if not defined PY (
  where python >nul 2>&1
  if !ERRORLEVEL!==0 (
    python -c "import sys; raise SystemExit(0)" >nul 2>&1
    if !ERRORLEVEL!==0 set "PY=python"
  )
)
if not defined PY (
  echo Error: Python not found. Install Python from python.org and disable the Store app-execution alias. >&2
  exit /b 1
)
%PY% "%AGENT_DIR%\yousini.py" %*
endlocal
