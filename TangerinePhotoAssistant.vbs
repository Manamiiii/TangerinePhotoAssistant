Option Explicit

Dim shell, fileSystem, projectRoot, launcher, command
Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")
projectRoot = fileSystem.GetParentFolderName(WScript.ScriptFullName)
launcher = fileSystem.BuildPath(projectRoot, "scripts\windows_launcher.ps1")
command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & launcher & """ -Mode Start"
shell.Run command, 0, False
