@echo off
setlocal
cd /d "%~dp0"

if /I "%~1"=="electron" goto electron_compat
if /I "%~1"=="compat" goto electron_compat

rem Preserve the established Electron/Inno entry points unchanged.
if /I "%~1"=="build-inno" goto electron_passthrough
if /I "%~1"=="inno" goto electron_passthrough
if /I "%~1"=="dist-inno" goto electron_passthrough
if /I "%~1"=="build-inno-skip" goto electron_passthrough

if not "%~1"=="" (
  echo Unknown option "%~1".
  echo Usage: RUN_ME.bat [electron^|compat] [arguments]
  echo        RUN_ME.bat [build-inno^|inno^|dist-inno^|build-inno-skip]
  exit /b 2
)

pushd "%~dp0studio\edmg-studio-winui"
dotnet run --project ".\EdmgStudio.WinUI.csproj" --launch-profile "EdmgStudio.WinUI (Package)" -p:Platform=x64
set "exit_code=%errorlevel%"
popd
exit /b %exit_code%

:electron_compat
shift
rem cmd.exe has no unbounded post-SHIFT %* expansion. The compatibility
rem launcher currently accepts fewer than nine positional arguments.
call "%~dp0studio\edmg-studio\RUN_ME.bat" %1 %2 %3 %4 %5 %6 %7 %8 %9
exit /b %errorlevel%

:electron_passthrough
call "%~dp0studio\edmg-studio\RUN_ME.bat" %*
exit /b %errorlevel%
