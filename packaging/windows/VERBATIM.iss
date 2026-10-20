; Inno Setup script — builds VERBATIM-<version>-Setup.exe from dist\VERBATIM (PyInstaller output).
; iscc /DAppVersion=2.0.0 packaging\windows\VERBATIM.iss
#ifndef AppVersion
  #define AppVersion "2.0.0"
#endif

[Setup]
AppId={{8C3E8F2B-6A1D-4C49-9E0B-9F1D7A11E5B1}
AppName=VERBATIM
AppVersion={#AppVersion}
AppPublisher=Infinite Story LLP
AppCopyright=Copyright (c) 2026 Infinite Story LLP. All rights reserved.
VersionInfoCompany=Infinite Story LLP
VersionInfoCopyright=Copyright (c) 2026 Infinite Story LLP
VersionInfoDescription=VERBATIM - an Infinite Story LLP product
AppPublisherURL=https://infinitestory.in
LicenseFile=..\..\LICENSE
DefaultDirName={localappdata}\Programs\VERBATIM
DefaultGroupName=VERBATIM
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=VERBATIM-{#AppVersion}-Setup
SetupIconFile=..\..\assets\VERBATIM.ico
UninstallDisplayIcon={app}\VERBATIM.exe
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
WizardStyle=modern
CloseApplications=yes
RestartApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "autoupdate"; Description: "Check for VERBATIM updates every week (recommended)"; GroupDescription: "Updates:"

[Files]
Source: "..\..\dist\VERBATIM\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\..\scripts\windows\*.bat"; DestDir: "{app}\scripts"; Flags: ignoreversion

[Icons]
Name: "{group}\VERBATIM"; Filename: "{app}\VERBATIM.exe"
Name: "{group}\Update VERBATIM"; Filename: "{app}\scripts\Update VERBATIM.bat"
Name: "{autodesktop}\VERBATIM"; Filename: "{app}\VERBATIM.exe"; Tasks: desktopicon

[Run]
Filename: "schtasks.exe"; Parameters: "/Create /F /SC WEEKLY /D MON /ST 10:00 /TN ""VERBATIM Updater"" /TR ""\""{app}\verbatim-cli.exe\"" --update --auto"""; Flags: runhidden; Tasks: autoupdate
Filename: "{app}\VERBATIM.exe"; Description: "Launch VERBATIM"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "schtasks.exe"; Parameters: "/Delete /F /TN ""VERBATIM Updater"""; Flags: runhidden; RunOnceId: "DelTask"
