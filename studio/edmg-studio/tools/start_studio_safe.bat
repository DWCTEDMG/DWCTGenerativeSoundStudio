@echo off
setlocal
cd /d "%~dp0\.." || exit /b 1
call pnpm run dev
exit /b %ERRORLEVEL%
