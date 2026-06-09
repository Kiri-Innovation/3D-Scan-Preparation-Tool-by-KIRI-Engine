; 3D Scan Prep Tool Windows installer recipe.
; Build with windows/build_inno_installer.ps1 after packaging the Electron app.

#define MyAppName "3D Scan Prep Tool"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "KIRI Tools"
#define MyAppURL "www.kiriengine.app"
#define MyAppExeName "3D Scan Prep Tool.exe"
#define MyAppIconName "KIRI Logo ICO.ico"
#define ProjectRoot AddBackslash(SourcePath) + "..\.."

[Setup]
AppId={{2A5303FA-2751-472B-B9DC-434BBABA5A9D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
UninstallDisplayIcon={app}\{#MyAppIconName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
LicenseFile={#ProjectRoot}\license.txt
OutputDir={#ProjectRoot}\Packaged
OutputBaseFilename=3D Scan Prep Tool
SetupIconFile={#ProjectRoot}\KIRI Logo ICO.ico
SolidCompression=yes
Compression=lzma2/ultra64
LZMAAlgorithm=1
WizardStyle=modern dynamic

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#ProjectRoot}\dist\3D Scan Prep Tool\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjectRoot}\dist\3D Scan Prep Tool\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppIconName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppIconName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

