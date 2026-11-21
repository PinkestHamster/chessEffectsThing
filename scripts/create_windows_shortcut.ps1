param(
  [Parameter(Mandatory = $true)]
  [string]$TargetPath,
  [Parameter(Mandatory = $true)]
  [string]$ShortcutPath
)

$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($ShortcutPath)
$shortcut.TargetPath = $TargetPath
$shortcut.WorkingDirectory = Split-Path -Parent $TargetPath
$shortcut.IconLocation = "$TargetPath,0"
$shortcut.Description = 'Chess Vision FX'
$shortcut.Save()
Write-Output "Created Windows shortcut: $ShortcutPath"
