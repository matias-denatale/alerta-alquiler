# ============================================================
#  Registra la Tarea Programada que corre el bot 6 veces al dia
#  (08:00, 12:00, 16:00, 18:00, 20:00 y 22:00). Ejecutar UNA vez.
#
#  Como usar:
#    1) Abri PowerShell en ESTA carpeta (Shift + click derecho > "Abrir ventana de PowerShell aqui")
#    2) Si te bloquea el script, corre primero:
#         Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#    3) Corre:  .\instalar_tarea_6x_dia.ps1
# ============================================================

$ErrorActionPreference = "Stop"
$carpeta = $PSScriptRoot
$bat     = Join-Path $carpeta "run_bot.bat"

if (-not (Test-Path $bat)) {
    Write-Host "No encuentro run_bot.bat en $carpeta" -ForegroundColor Red
    exit 1
}

$accion = New-ScheduledTaskAction -Execute $bat -WorkingDirectory $carpeta

# Seis disparos diarios
$t1 = New-ScheduledTaskTrigger -Daily -At 8:00am
$t2 = New-ScheduledTaskTrigger -Daily -At 12:00pm
$t3 = New-ScheduledTaskTrigger -Daily -At 4:00pm
$t4 = New-ScheduledTaskTrigger -Daily -At 6:00pm
$t5 = New-ScheduledTaskTrigger -Daily -At 8:00pm
$t6 = New-ScheduledTaskTrigger -Daily -At 10:00pm

# Que corra aunque estuvo apagada la PC a esa hora (se ejecuta al prender)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName "AlertaAlquilerCABA" `
    -Action $accion -Trigger $t1,$t2,$t3,$t4,$t5,$t6 -Settings $settings `
    -Description "Busca alquileres en CABA y avisa por Telegram (6x/dia)" `
    -Force

Write-Host ""
Write-Host "Tarea 'AlertaAlquilerCABA' creada. Corre a las 08:00, 12:00, 16:00, 18:00, 20:00 y 22:00." -ForegroundColor Green
Write-Host "Para probarla ahora mismo:  Start-ScheduledTask -TaskName AlertaAlquilerCABA" -ForegroundColor Yellow
