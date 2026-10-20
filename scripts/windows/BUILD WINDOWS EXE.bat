@echo off
rem Builds dist\VERBATIM-<version>-Setup.exe on Windows 10/11 (needs Python 3.12 and Inno Setup 6).
cd /d "%~dp0..\.."
py -3.12 -m venv .buildvenv || (echo Install Python 3.12 from python.org & pause & exit /b 1)
call .buildvenv\Scripts\activate
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements-dev.txt || (pause & exit /b 1)
python -m pytest -q tests || (echo Tests failed & pause & exit /b 1)
for /f %%v in ('python -c "import verbatim;print(verbatim.__version__)"') do set VERSION=%%v
pyinstaller --noconfirm --clean packaging\VERBATIM.spec || (pause & exit /b 1)
dist\VERBATIM\verbatim-cli.exe --version
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" ( echo Inno Setup 6 not found - install from jrsoftware.org, or use the portable folder dist\VERBATIM & pause & exit /b 1 )
"%ISCC%" /DAppVersion=%VERSION% packaging\windows\VERBATIM.iss
certutil -hashfile dist\VERBATIM-%VERSION%-Setup.exe SHA256
echo Installer ready: dist\VERBATIM-%VERSION%-Setup.exe
pause
