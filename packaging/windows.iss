; Inno Setup script; the build passes Version, SourceDir and OutputDir.
[Setup]
; Fixed on purpose: it names the uninstall entry ("Bot Widget_is1") and lets an update find the
; earlier install. This is the value every release so far used by default; changing it would leave
; existing installs with a second, orphaned entry in Installed apps.
AppId=Bot Widget
AppName=Bot Widget
AppPublisher=Bot Widget
AppVersion={#Version}
VersionInfoVersion={#Version}
VersionInfoProductName=Bot Widget
VersionInfoProductVersion={#Version}
VersionInfoProductTextVersion={#Version}
DefaultDirName={localappdata}\Programs\Bot Widget
DefaultGroupName=Bot Widget
PrivilegesRequired=lowest
DisableWelcomePage=yes
Uninstallable=yes
OutputDir={#OutputDir}
OutputBaseFilename=BotWidget-Windows-Setup
Compression=lzma2
SolidCompression=yes
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=yes
; The app inside is 64-bit x64 (it also runs on Windows on Arm through emulation).
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Only for a SignPath release: the uninstaller is signed outside Inno and then embedded.
#ifdef SignedUninstall
SignedUninstaller=yes
SignedUninstallerDir={#SignedUninstallerDir}
#endif
; The installer's own icon in Explorer and Search, unless no .ico was passed.
#ifndef IconFile
  #define IconFile "icon.ico"
#endif
SetupIconFile={#IconFile}

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Bot Widget"; Filename: "{app}\Bot Widget.exe"; IconFilename: "{app}\icon.ico"

[Run]
Filename: "{app}\Bot Widget.exe"; Description: "Start Bot Widget"; Flags: nowait postinstall skipifsilent
