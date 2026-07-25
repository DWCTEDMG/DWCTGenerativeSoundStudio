@echo off
setlocal
cd /d %~dp0

if /I "%~1"=="build-inno" goto build_inno
if /I "%~1"=="inno" goto build_inno
if /I "%~1"=="dist-inno" goto build_inno
if /I "%~1"=="build-inno-skip" goto build_inno_skip

if defined EDMG_STUDIO_PYTHON (
  "%EDMG_STUDIO_PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 10) else 1)" >nul 2>nul
  if %errorlevel%==0 (
    "%EDMG_STUDIO_PYTHON%" tools\run_uv_launcher.py
    goto :eof
  )
)

where py >nul 2>nul
if %errorlevel%==0 (
  py -3.12 -c "import sys" >nul 2>nul && (py -3.12 tools\run_uv_launcher.py & goto :eof)
  py -3 -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 10) else 1)" >nul 2>nul && (py -3 tools\run_uv_launcher.py & goto :eof)
)

where python >nul 2>nul
if %errorlevel%==0 (
  python -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 10) else 1)" >nul 2>nul && (python tools\run_uv_launcher.py & goto :eof)
)

echo Could not find Python 3.10+ to bootstrap the pinned uv toolchain.
echo The source launcher uses uv 0.11.28 to acquire and run Python 3.12.
echo Set EDMG_STUDIO_PYTHON to a bootstrap python.exe and run again.
pause

goto :eof

:build_inno
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0packaging\windows\build_inno_external.ps1"
if errorlevel 1 pause
goto :eof

:build_inno_skip
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0packaging\windows\build_inno_external.ps1" -SkipElectronDirBuild
if errorlevel 1 pause
