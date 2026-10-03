param([switch]$Preview)
$ErrorActionPreference = 'Stop'
try {
    $module = Get-ChildItem -LiteralPath $PSScriptRoot -Directory |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'desktop_guard.py') } |
        Select-Object -First 1
    if (-not $module) { throw 'Desktop module was not found.' }
    $runtime = Join-Path $module.FullName '.venv\Scripts\pythonw.exe'
    if (-not (Test-Path -LiteralPath $runtime)) { throw 'Prepare the desktop Python environment before launching.' }
    $entry = Join-Path $PSScriptRoot 'VisionShield.py'
    $arguments = '"' + $entry + '"'
    if ($Preview) { $arguments += ' --preview' }
    Start-Process -FilePath $runtime -ArgumentList $arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
} catch {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'VisionShield launch error') | Out-Null
    exit 1
}
