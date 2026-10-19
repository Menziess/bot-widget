; Inno Setup-script; de build geeft Version, SourceDir en OutputDir mee.
[Setup]
AppName=Bot Widget
AppVersion={#Version}
DefaultDirName={localappdata}\Programs\Bot Widget
DefaultGroupName=Bot Widget
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=BotWidget-Windows-Setup
Compression=lzma2
SolidCompression=yes
DisableProgramGroupPage=yes

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Bot Widget"; Filename: "{app}\Bot Widget.exe"

[Run]
Filename: "{app}\Bot Widget.exe"; Description: "Start Bot Widget"; Flags: nowait postinstall skipifsilent
