param([Parameter(Mandatory=$true)][string]$CurrentOutput, [switch]$Apply)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
if (-not (Test-Path -LiteralPath (Join-Path $repo 'VisionShield.py'))) { throw 'Not a VisionShield repository.' }
if ($CurrentOutput -notmatch '^[A-Za-z0-9_-]+$') { throw 'Invalid output name.' }
$cutoff = [DateTime]::UtcNow.AddHours(-24)
$receipts = @()
Get-ChildItem -LiteralPath (Join-Path $repo 'dist\.verified') -Filter '*.json' -ErrorAction SilentlyContinue | ForEach-Object {
    try {
        $record = Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($record.output_name -notmatch '^[A-Za-z0-9_-]+$' -or $record.passed -ne $true) { return }
        $exe = Join-Path $repo "dist\$($record.output_name)\VisionShield\VisionShield.exe"
        if ((Test-Path -LiteralPath $exe) -and (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash -eq $record.exe_sha256) {
            $receipts += $record
        }
    } catch { } # Invalid old receipts never authorize deletion.
}
if (-not @($receipts | Where-Object { $_.output_name -eq $CurrentOutput }).Count) { throw 'Current package must pass verification before cleanup.' }
$rollback = $receipts | Where-Object { $_.output_name -ne $CurrentOutput } | Sort-Object verified_at_utc -Descending | Select-Object -First 1
$keep = @($CurrentOutput)
if ($rollback) { $keep += $rollback.output_name }
$keepHashes = @($receipts | Where-Object { $_.output_name -in $keep } | ForEach-Object { $_.exe_sha256 })
$running = @(Get-Process -Name VisionShield -ErrorAction SilentlyContinue)
Add-Type -AssemblyName System.IO.Compression.FileSystem
function Get-OldCandidate($item, $container) {
    $absolute = [IO.Path]::GetFullPath($item.FullName)
    $parent = [IO.Path]::GetFullPath((Join-Path $repo $container))
    if ([IO.Path]::GetDirectoryName($absolute) -ne $parent) { throw 'Artifact escaped its permitted directory.' }
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { return }
    $children = @()
    if ($item.PSIsContainer) {
        $children = @(Get-ChildItem -LiteralPath $absolute -Recurse -Force)
        if (@($children | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) { return }
        if (@($children | Where-Object { ($_.PSIsContainer -and $_.Name -in @('private','records','.venv','screenshots','captures')) -or $_.Extension -eq '.npz' }).Count) { return }
    }
    if (@(@($item) + $children | Where-Object { $_.LastWriteTimeUtc -ge $cutoff }).Count) { return }
    foreach ($active in $running) {
        if (-not $active.Path) { return }
        if ($active.Path.StartsWith($absolute + '\', [StringComparison]::OrdinalIgnoreCase) -or $active.Path -eq $absolute) { return }
    }
    $bytes = if ($item.PSIsContainer) { ($children | Where-Object { -not $_.PSIsContainer } | Measure-Object Length -Sum).Sum } else { $item.Length }
    [PSCustomObject]@{ path=$absolute; bytes=[long]$bytes }
}
$candidates = @()
foreach ($container in @('dist','build')) {
    Get-ChildItem -LiteralPath (Join-Path $repo $container) -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.Name -notmatch '^windows-[A-Za-z0-9_-]+$' -or $_.Name -in $keep) { return }
        $marker = if ($container -eq 'dist') { 'VisionShield\VisionShield.exe' } else { 'VisionShield\Analysis-00.toc' }
        if (Test-Path -LiteralPath (Join-Path $_.FullName $marker)) {
            $candidate = Get-OldCandidate $_ $container
            if ($candidate) { $candidates += $candidate }
        }
    }
}
Get-ChildItem -LiteralPath (Join-Path $repo 'dist') -Filter 'VisionShield-Windows-*.zip' -File | ForEach-Object {
    $candidate = Get-OldCandidate $_ 'dist'
    if (-not $candidate) { return }
    $archive = $null; $stream = $null; $hasher = $null
    try {
        $archive = [IO.Compression.ZipFile]::OpenRead($_.FullName)
        $entry = $archive.GetEntry('VisionShield/VisionShield.exe')
        if (-not $entry) { return }
        $stream = $entry.Open(); $hasher = [Security.Cryptography.SHA256]::Create()
        $hash = [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-','')
        if ($hash -notin $keepHashes) { $candidates += $candidate }
    } catch { } finally {
        if ($stream) { $stream.Dispose() }; if ($archive) { $archive.Dispose() }; if ($hasher) { $hasher.Dispose() }
    }
}
# Every candidate was checked to be a direct child of this repository's dist/build.
# Native PowerShell deletion preserves literal paths and never crosses reparse points.
foreach ($candidate in $candidates) {
    if ($Apply) { Remove-Item -LiteralPath $candidate.path -Recurse -Force }
}
$summary = @{ applied=[bool]$Apply; kept_outputs=$keep; candidates=$candidates; bytes=($candidates | Measure-Object bytes -Sum).Sum }
if ($Apply) {
    $evidence = Join-Path $repo 'test_artifacts'
    New-Item -ItemType Directory -Force -Path $evidence | Out-Null
    $summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $evidence ('cleanup-' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss') + '.json')) -Encoding UTF8
}
$summary | ConvertTo-Json -Depth 5
