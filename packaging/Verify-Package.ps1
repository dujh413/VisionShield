param([Parameter(Mandatory=$true)][string]$OutputName)
$ErrorActionPreference = 'Stop'
if ($OutputName -notmatch '^[A-Za-z0-9_-]+$') { throw 'Invalid output name.' }
$repo = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $repo "dist\$OutputName\VisionShield\VisionShield.exe"
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw 'Package executable is missing.' }
$evidence = Join-Path $repo 'test_artifacts'
New-Item -ItemType Directory -Force -Path $evidence | Out-Null
$report = Join-Path $evidence ('package-' + $OutputName + '-' + [guid]::NewGuid().ToString('N') + '.json')
$hash = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash
$process = Start-Process -FilePath $exe -ArgumentList @('--package-check', ('"' + $report + '"')) -WindowStyle Hidden -PassThru
if (-not $process.WaitForExit(120000)) {
    $process.Kill()
    throw 'Package verification timed out. No cleanup performed.'
}
$process.Refresh()
if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $report)) { throw 'Package verification failed. No cleanup performed.' }
$result = Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json
if ($result.passed -ne $true -or $result.frozen -ne $true -or
    $result.region_tracking.passed -ne $true -or
    @($result.checks.PSObject.Properties).Count -ne 12 -or
    @($result.checks.PSObject.Properties | Where-Object { $_.Value -ne $true }).Count -ne 0 -or
    (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash -ne $hash) { throw 'Invalid or changed package verification result.' }
$receipts = Join-Path $repo 'dist\.verified'
New-Item -ItemType Directory -Force -Path $receipts | Out-Null
@{ output_name=$OutputName; exe_sha256=$hash; passed=$true; verified_at_utc=[DateTime]::UtcNow.ToString('o') } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $receipts ($OutputName + '.json')) -Encoding UTF8
Write-Output "Verified: $OutputName (12 checks, two start/stop cycles)."
