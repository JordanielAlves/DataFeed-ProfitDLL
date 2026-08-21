# Script para configurar inicializacao automatica via Windows Task Scheduler
# Para rodar, abra um PowerShell como Administrador e execute: .\setup_scheduler.ps1

$action = New-ScheduledTaskAction -Execute "C:\DEV\ProfitDLL\start_system.bat"
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

Register-ScheduledTask -TaskName "DataFeed-B3-AutoStart" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force

Write-Host "Tarefa DataFeed-B3-AutoStart configurada com sucesso!" -ForegroundColor Green
