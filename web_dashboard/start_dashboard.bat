@echo off
title ProfitDLL Quantitative Dashboard
echo ===================================================
echo   Iniciando Dashboard Quantitativo ProfitDLL / B3
echo ===================================================
cd /d C:\DEV\ProfitDLL\web_dashboard\backend
echo Servidor Web + API + WebSockets rodando em:
echo   http://localhost:8000
echo.
start "ProfitDLL-Dashboard-API" cmd /k "python -u server.py"
timeout /t 3 /nobreak >nul
start http://localhost:8000
echo.
echo Dashboard aberto no navegador! Feche esta janela se desejar.
pause
