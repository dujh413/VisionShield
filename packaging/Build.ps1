param([string]$Python, [string]$OutputName = 'windows-test')
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
if (-not $Python) {
    $module = Get-ChildItem -LiteralPath $repo -Directory |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'desktop_guard.py') } |
        Select-Object -First 1
    $Python = Join-Path $module.FullName '.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $Python)) { throw 'Specify -Python with the prepared build environment.' }
if ($OutputName -notmatch '^[A-Za-z0-9_-]+$') { throw 'OutputName must be a simple folder name.' }
$destination = Join-Path $repo ('dist\' + $OutputName)
$work = Join-Path $repo ('build\' + $OutputName)
if (Test-Path -LiteralPath $destination) { throw 'Output exists. Use a new OutputName to preserve prior packages.' }
$originalPath = $env:PATH
try {
    # 避免其他工具的同名DLL被误收集进包，尤其是非Windows ICU库。
    $env:PATH = (Split-Path -Parent $Python) + ';' + $env:SystemRoot + '\System32;' + $env:SystemRoot
    & $Python -m PyInstaller --noconfirm --distpath $destination --workpath $work (Join-Path $PSScriptRoot 'VisionShield.spec')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
} finally {
    $env:PATH = $originalPath
}
$readme = Get-ChildItem -LiteralPath (Join-Path $repo 'docs') -Filter 'Windows*.md' | Select-Object -First 1
if ($readme) { Copy-Item -LiteralPath $readme.FullName -Destination (Join-Path $destination 'VisionShield\README.md') }
Write-Output (Join-Path $destination 'VisionShield\VisionShield.exe')
