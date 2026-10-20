@echo off
rem Checks for a newer VERBATIM, verifies it (SHA-256 + signature) and installs it.
setlocal
set "APP=%LOCALAPPDATA%\Programs\VERBATIM\verbatim-cli.exe"
if exist "%~dp0..\verbatim-cli.exe" set "APP=%~dp0..\verbatim-cli.exe"
if exist "%APP%" (
  "%APP%" --update %*
) else if exist "%~dp0..\..\.venv\Scripts\python.exe" (
  "%~dp0..\..\.venv\Scripts\python.exe" "%~dp0..\..\run.py" --update %*
) else (
  echo VERBATIM is not installed.
)
echo %* | find "--auto" >nul || pause
