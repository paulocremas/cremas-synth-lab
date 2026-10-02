; Instalador do PRISMA! pro Windows (Inno Setup 6). Gerado pelo CI (.github/workflows/release.yml):
;   iscc /DAppVersion=0.2.0 /DSrcDir=..\dist\prisma /DOutDir=..\dist packaging\prisma.iss
; Instala POR USUARIO (sem admin) em %LOCALAPPDATA%\Programs\PRISMA; dados do usuario ficam em
; %LOCALAPPDATA%\prisma (ver packaging/launcher.py) e sobrevivem a atualizacao/desinstalacao.
; Atualizacao = rodar o instalador novo por cima (o app baixa e abre ele; ver packaging/updater.py).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SrcDir
  #define SrcDir "..\dist\prisma"
#endif
#ifndef OutDir
  #define OutDir "..\dist"
#endif

[Setup]
AppId={{7C1E4A52-9B3D-4F6A-8E21-5D0C3B9A7F14}
AppName=PRISMA!
AppVersion={#AppVersion}
AppVerName=PRISMA! {#AppVersion}
AppPublisher=cremas
AppPublisherURL=https://github.com/paulocremas/cremas-synth-lab
DefaultDirName={localappdata}\Programs\PRISMA
DefaultGroupName=PRISMA!
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutDir}
OutputBaseFilename=PRISMA-{#AppVersion}-setup
SetupIconFile=..\build\prisma.ico
UninstallDisplayIcon={app}\prisma.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; atualizacao com o app aberto: fecha ele antes de copiar
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; versao anterior: o PyInstaller muda nomes de dll entre builds — limpa o runtime antigo
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SrcDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\PRISMA!"; Filename: "{app}\prisma.exe"
Name: "{group}\{cm:UninstallProgram,PRISMA!}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\PRISMA!"; Filename: "{app}\prisma.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\prisma.exe"; Description: "{cm:LaunchProgram,PRISMA!}"; Flags: nowait postinstall skipifsilent
