@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title almas projekt - Telegram bot setup
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0SETUP_BOT.ps1"
echo.
if errorlevel 1 (
  echo Баптау кезінде қате шықты.
) else (
  echo Баптау аяқталды.
)
pause
