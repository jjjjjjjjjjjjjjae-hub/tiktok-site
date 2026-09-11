@echo off
setlocal
cd /d "%~dp0"
where node >nul 2>nul
if errorlevel 1 goto no_node
node -e "if(Number(process.versions.node.split('.')[0])<24)process.exit(1)"
if errorlevel 1 goto no_node
node server\index.mjs --open %*
if errorlevel 1 pause
exit /b
:no_node
echo Node.js 24 or newer is required. Install it from https://nodejs.org/
pause
exit /b 1
