# Stop Vectiq and remove its scheduled task. Your data\ folder (database, identity) and .env are kept.
Stop-ScheduledTask -TaskName Vectiq -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName Vectiq -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "Vectiq stopped and its scheduled task removed. Delete this folder to remove everything, including data\ and .env."
