#ifndef AppVersion
  #define AppVersion "1.3.0-beta.2"
#endif
#ifndef WindowsVersion
  #define WindowsVersion "1.3.0.2"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\portable\OVID Converter"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{9AB05BAE-74B4-48C6-AB2B-D5E8344C3E6A}
AppName=OVID Converter
AppVersion={#AppVersion}
AppVerName=OVID Converter v{#AppVersion}
AppPublisher=riochihao
AppPublisherURL=https://github.com/akasa828/SD_Card_OVID_Player
AppSupportURL=https://github.com/akasa828/SD_Card_OVID_Player/issues
AppUpdatesURL=https://github.com/akasa828/SD_Card_OVID_Player/releases
DefaultDirName={localappdata}\Programs\OVID Converter
DefaultGroupName=OVID Converter
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=OVID_Converter_Windows_x64_Setup_v{#AppVersion}
SetupIconFile=..\build\ovid_converter.ico
UninstallDisplayIcon={app}\OVID Converter.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
VersionInfoVersion={#WindowsVersion}
VersionInfoCompany=riochihao
VersionInfoDescription=Material 3 media to OVID v2 converter
VersionInfoProductName=OVID Converter
VersionInfoProductVersion={#WindowsVersion}
LicenseFile=..\..\LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "chinesesimplified"; MessagesFile: ".\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\OVID Converter"; Filename: "{app}\OVID Converter.exe"
Name: "{autodesktop}\OVID Converter"; Filename: "{app}\OVID Converter.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\OVID Converter.exe"; Description: "{cm:LaunchProgram,OVID Converter}"; Flags: nowait postinstall skipifsilent
