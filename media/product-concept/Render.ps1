param(
    [string]$Python,
    [switch]$PreviewOnly,
    [switch]$Silent
)
$ErrorActionPreference = 'Stop'
if (-not $Python) {
    $Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $Python)) {
    throw 'Specify -Python with a Python interpreter containing requirements.txt, or create the local .venv described in README.md.'
}
& $Python (Join-Path $PSScriptRoot 'capture_ui.py')
if ($LASTEXITCODE -ne 0) { throw 'Controlled UI export failed.' }
if (-not $Silent) {
    & $Python (Join-Path $PSScriptRoot 'soundtrack.py')
    if ($LASTEXITCODE -ne 0) { throw 'Soundtrack generation failed.' }
}
$taskArguments = @((Join-Path $PSScriptRoot 'render.py'))
if ($PreviewOnly) { $taskArguments += '--preview-only' }
if ($Silent) { $taskArguments += '--silent' }
& $Python @taskArguments
if ($LASTEXITCODE -ne 0) { throw 'Video rendering failed.' }
if (-not $PreviewOnly) {
    $taskVerifyArguments = @((Join-Path $PSScriptRoot 'verify.py'))
    if ($Silent) { $taskVerifyArguments += '--silent' }
    & $Python @taskVerifyArguments
    if ($LASTEXITCODE -ne 0) { throw 'Video verification failed.' }
}
