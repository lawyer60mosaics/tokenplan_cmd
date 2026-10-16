#define AppVersion "1.1.0"
[Setup]
AppId={{C3D190EA-A278-4AFA-A87E-26641D5B0965}
AppName=XCLI TokenPlan
AppVersion={#AppVersion}
AppPublisher=TokenPlan
AppPublisherURL=https://github.com/lawyer60mosaics/tokenplan_cmd
DefaultDirName={localappdata}\Programs\XCLI
DefaultGroupName=XCLI
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=XCLI-{#AppVersion}-Setup-x64
Compression=lzma2
SolidCompression=yes
ChangesEnvironment=yes
UninstallDisplayIcon={app}\xcli.exe
WizardStyle=modern
[Files]
Source: "..\dist\xcli.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\NOTICE.md"; DestDir: "{app}"; Flags: ignoreversion
[Icons]
Name: "{group}\XCLI"; Filename: "{app}\xcli.exe"
Name: "{group}\Configure XCLI"; Filename: "{app}\xcli.exe"; Parameters: "--configure"
[Code]
function WithoutAppPath(Value: String): String;
var Item, ResultValue, AppPath: String; Index: Integer;
begin
  AppPath := ExpandConstant('{app}');
  ResultValue := '';
  while Value <> '' do begin
    Index := Pos(';', Value);
    if Index = 0 then Index := Length(Value) + 1;
    Item := Copy(Value, 1, Index - 1);
    Delete(Value, 1, Index);
    if CompareText(RemoveBackslashUnlessRoot(RemoveQuotes(Trim(Item))), RemoveBackslashUnlessRoot(AppPath)) <> 0 then begin
      if ResultValue <> '' then ResultValue := ResultValue + ';';
      ResultValue := ResultValue + Item;
    end;
  end;
  Result := ResultValue;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var CurrentPath: String;
begin
  if CurStep = ssPostInstall then begin
    RegQueryStringValue(HKCU, 'Environment', 'Path', CurrentPath);
    CurrentPath := WithoutAppPath(CurrentPath);
    if CurrentPath <> '' then CurrentPath := CurrentPath + ';';
    if not RegWriteExpandStringValue(HKCU, 'Environment', 'Path', CurrentPath + ExpandConstant('{app}')) then
      RaiseException('Unable to update user PATH.');
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var CurrentPath: String;
begin
  if CurUninstallStep = usPostUninstall then begin
    if RegQueryStringValue(HKCU, 'Environment', 'Path', CurrentPath) then
      RegWriteExpandStringValue(HKCU, 'Environment', 'Path', WithoutAppPath(CurrentPath));
  end;
end;
