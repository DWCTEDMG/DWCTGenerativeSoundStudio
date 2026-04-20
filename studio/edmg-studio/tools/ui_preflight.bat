@echo off
setlocal
cd /d "%~dp0\.." || exit /b 1
echo === UI PREFLIGHT: pnpm run typecheck ===
call pnpm run typecheck
exit /b %ERRORLEVEL%
