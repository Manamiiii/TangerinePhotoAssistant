Unicode true
ManifestDPIAware true
RequestExecutionLevel user
SetCompressor /SOLID lzma
!include "MUI2.nsh"
!include "x64.nsh"
!include "LogicLib.nsh"
!ifndef PRODUCT_NAME
  !define PRODUCT_NAME "TangerinePhotoAssistant"
!endif
!ifndef PRODUCT_KEY
  !define PRODUCT_KEY "{551A03F7-2773-4A5E-962C-6BBDB8B28E08}"
!endif
Name "${PRODUCT_NAME}"
OutFile "${SETUP_OUTPUT}"
InstallDir "$LOCALAPPDATA\Programs\${PRODUCT_NAME}"
InstallDirRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_KEY}" "InstallLocation"
VIProductVersion "${SETUP_VERSION}.0"
VIAddVersionKey "ProductName" "${PRODUCT_NAME}"
VIAddVersionKey "FileDescription" "${PRODUCT_NAME} per-user Setup"
VIAddVersionKey "FileVersion" "${SETUP_VERSION}"
VIAddVersionKey "LegalCopyright" "Copyright 2026 Manamiiii; GPL-3.0-only"
Icon "${PROJECT_ROOT}\assets\tangerine-photo-assistant.ico"
UninstallIcon "${PROJECT_ROOT}\assets\tangerine-photo-assistant.ico"
!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${PROJECT_ROOT}\LICENSE"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"

Function .onInit
  SetShellVarContext current
  SetRegView 64
  System::Call 'kernel32::CreateMutexW(p 0, i 0, w "Local\${PRODUCT_KEY}-maintenance") p .r1 ?e'
  Pop $0
  ${If} $0 = 183
    SetErrorLevel 22
    Quit
  ${EndIf}
  ${IfNot} ${RunningX64}
    MessageBox MB_OK|MB_ICONSTOP "This package requires Windows x64." /SD IDOK
    SetErrorLevel 10
    Quit
  ${EndIf}
FunctionEnd

Section "Install"
  InitPluginsDir
  SetOutPath "$PLUGINSDIR\payload"
  File /r "${BUNDLE}\*"
  nsExec::ExecToLog '"$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\payload\setup_windows_app.ps1" -Action Install -InstallRoot "$INSTDIR" -ProductName "${PRODUCT_NAME}" -ProductKey "${PRODUCT_KEY}" -DisplayVersion "${SETUP_VERSION}"'
  Pop $0
  ${If} $0 != 0
    MessageBox MB_OK|MB_ICONSTOP "Installation was refused or failed. Close the application and safely stop its idle background service, then retry. Your data was preserved. See Details for the reason." /SD IDOK
    SetErrorLevel 20
    Abort
  ${EndIf}
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_KEY}" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_KEY}" "QuietUninstallString" '$\"$INSTDIR\Uninstall.exe$\" /S'
SectionEnd

Function un.onInit
  SetShellVarContext current
  SetRegView 64
  System::Call 'kernel32::CreateMutexW(p 0, i 0, w "Local\${PRODUCT_KEY}-maintenance") p .r1 ?e'
  Pop $0
  ${If} $0 = 183
    SetErrorLevel 22
    Quit
  ${EndIf}
FunctionEnd

Section "Uninstall"
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  ; Embed trusted maintenance code; never execute unknown code from user data.
  File "${PROJECT_ROOT}\scripts\setup_windows_app.ps1"
  File "${PROJECT_ROOT}\scripts\windows_package_common.ps1"
  File "${PROJECT_ROOT}\scripts\manage_windows_app.ps1"
  nsExec::ExecToLog '"$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\setup_windows_app.ps1" -Action Uninstall -InstallRoot "$INSTDIR" -ProductName "${PRODUCT_NAME}" -ProductKey "${PRODUCT_KEY}"'
  Pop $0
  ${If} $0 != 0
    MessageBox MB_OK|MB_ICONSTOP "Uninstall was refused or incomplete. Safely stop the application and its background service, then retry. No process was killed. Your data was preserved." /SD IDOK
    SetErrorLevel 21
    Abort
  ${EndIf}
  Delete "$INSTDIR\Uninstall.exe"
  ; No recursive directory deletion: receipts and any user-added files remain.
SectionEnd
