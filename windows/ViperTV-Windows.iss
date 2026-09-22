#ifndef MyAppVersion
  #define MyAppVersion "1.5.0"
#endif
#define MyAppName "ViperTV"
#define MyAppPublisher "Darren 'The Viper' Crawford"
#define Stage GetEnv("VIPERTV_STAGE")
#define Out GetEnv("VIPERTV_OUT")

[Setup]
AppId={{9D7E99F3-4B6D-4C12-9F2B-56AFC6191500}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\ViperTV
DefaultGroupName=ViperTV
UninstallDisplayName=ViperTV {#MyAppVersion}
OutputDir={#Out}
OutputBaseFilename=ViperTV-v{#MyAppVersion}-Windows-x64-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
DisableProgramGroupPage=yes
SetupLogging=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "autostart"; Description: "Start ViperTV when I sign in to Windows"; GroupDescription: "Startup:"; Flags: unchecked
Name: "firewall"; Description: "Allow ViperTV through Windows Firewall on TCP port 8409"; GroupDescription: "Network access:"; Flags: unchecked

[Files]
Source: "{#Stage}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "portable.mode;UserData\*;dist-windows\*;_build\*"
Source: "{#Stage}\windows\installed.mode"; DestDir: "{app}"; DestName: "installed.mode"; Flags: ignoreversion

[Dirs]
Name: "{commonappdata}\ViperTV"; Permissions: users-modify
Name: "{commonappdata}\ViperTV\data"
Name: "{commonappdata}\ViperTV\logs"
Name: "{commonappdata}\ViperTV\backups-secondary"
Name: "{commonappdata}\ViperTV\updates"

[Icons]
Name: "{group}\Start ViperTV"; Filename: "{app}\ViperTV.exe"; Parameters: "start"; WorkingDir: "{app}"
Name: "{group}\Open ViperTV"; Filename: "{app}\ViperTV.exe"; Parameters: "open"; WorkingDir: "{app}"
Name: "{group}\Restart ViperTV"; Filename: "{app}\ViperTV.exe"; Parameters: "restart"; WorkingDir: "{app}"
Name: "{group}\Stop ViperTV"; Filename: "{app}\ViperTV.exe"; Parameters: "stop"; WorkingDir: "{app}"
Name: "{group}\ViperTV Logs"; Filename: "{app}\ViperTV.exe"; Parameters: "logs"; WorkingDir: "{app}"
Name: "{autodesktop}\ViperTV"; Filename: "{app}\ViperTV.exe"; Parameters: "start"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\ViperTV"; Filename: "{app}\ViperTV.exe"; Parameters: "start-silent"; WorkingDir: "{app}"; Tasks: autostart

[Run]
Filename: "{cmd}"; Parameters: "/c netsh advfirewall firewall delete rule name=""ViperTV TCP 8409"" >nul 2>&1 & netsh advfirewall firewall add rule name=""ViperTV TCP 8409"" dir=in action=allow protocol=TCP localport=8409"; Flags: runhidden; Tasks: firewall
Filename: "{app}\ViperTV.exe"; Parameters: "start"; Description: "Start ViperTV now"; Flags: postinstall nowait skipifsilent runasoriginaluser

[UninstallRun]
Filename: "{app}\ViperTV.exe"; Parameters: "stop-silent"; Flags: runhidden; RunOnceId: "StopViperTV"
Filename: "{cmd}"; Parameters: "/c netsh advfirewall firewall delete rule name=""ViperTV TCP 8409"" >nul 2>&1"; Flags: runhidden; RunOnceId: "RemoveFirewall"

[UninstallDelete]
; Deliberately do NOT delete {commonappdata}\ViperTV. User database/backups survive uninstall.
Type: filesandordirs; Name: "{app}"
