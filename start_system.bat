@echo off
title DataFeed B3 - Sistema de Coleta
echo Iniciando DataFeed B3...
cd /d C:\DEV\ProfitDLL
start "DataFeed-Main" cmd /k "python -u main.py"
timeout /t 3 /nobreak >nul
start "DataFeed-Watchdog" cmd /k "python -u watchdog.py"
echo Sistema iniciado. Feche esta janela ou pressione qualquer tecla.
pause
