#define AppName "Spoty Discord Bot"
#define AppPublisher "Spoty"
#define AppExeName "SpotyDiscordBot.exe"
#define SourceDir GetEnv("SPOTY_APP_SOURCE")
#define OutputDir GetEnv("SPOTY_INSTALLER_OUTPUT")
#define AppVersion GetEnv("SPOTY_APP_VERSION")

[Setup]
AppId={{D50722AC-17B6-42C9-9297-AD3D2EEA8B5D}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\Spoty
DefaultGroupName=Spoty
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=SpotySetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\{#AppExeName}

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Spoty Discord Bot"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\Spoty Discord Bot"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch Spoty Discord Bot"; Flags: nowait postinstall skipifsilent
