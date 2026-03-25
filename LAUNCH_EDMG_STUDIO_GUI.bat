@echo off
setlocal
cd /d %~dp0
echo LAUNCH_EDMG_STUDIO_GUI.bat is now a compatibility alias.
echo Redirecting to RUN_ME.bat...
call "%~dp0RUN_ME.bat"
exit /b %ERRORLEVEL%
