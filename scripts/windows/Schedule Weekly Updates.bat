@echo off
rem Creates a Windows scheduled task that checks for VERBATIM updates every Monday 10:00.
rem Run with  /remove  to delete it.
if /I "%1"=="/remove" ( schtasks /Delete /F /TN "VERBATIM Updater" & pause & exit /b )
set "APP=%LOCALAPPDATA%\Programs\VERBATIM\verbatim-cli.exe"
schtasks /Create /F /SC WEEKLY /D MON /ST 10:00 /TN "VERBATIM Updater" /TR "\"%APP%\" --update --auto"
echo Weekly update check scheduled.
pause
