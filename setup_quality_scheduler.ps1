# Script para agendar o quality check as 18:30 (dias uteis)
# Para rodar, abra um PowerShell como Administrador e execute: .\setup_quality_scheduler.ps1

$action = New-ScheduledTaskAction -Execute "python.exe" -Argument "C:\DEV\ProfitDLL\daily_quality_check.py" -WorkingDirectory "C:\DEV\ProfitDLL"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "18:30"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName "DataFeed-B3-QualityCheck" -Action $action -Trigger $trigger -Settings $settings -Force

Write-Host "Tarefa DataFeed-B3-QualityCheck configurada com sucesso!" -ForegroundColor Green
