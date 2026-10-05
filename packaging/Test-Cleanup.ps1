$ErrorActionPreference = 'Stop'
$fixture = Join-Path ([IO.Path]::GetTempPath()) ('VisionShield-cleanup-test-' + [guid]::NewGuid().ToString('N'))
$fixture = [IO.Path]::GetFullPath($fixture)
New-Item -ItemType Directory -Path (Join-Path $fixture 'packaging') | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Clean-Artifacts.ps1') -Destination (Join-Path $fixture 'packaging\Clean-Artifacts.ps1')
Set-Content -LiteralPath (Join-Path $fixture 'VisionShield.py') -Value '# fictional repository'
$old = [DateTime]::UtcNow.AddDays(-2)
function Make-Package($name, $content, $age) {
    $directory = Join-Path $fixture "dist\$name\VisionShield"
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    Set-Content -LiteralPath (Join-Path $directory 'VisionShield.exe') -Value $content
    if ($age) {
        Get-ChildItem -LiteralPath (Split-Path -Parent $directory) -Recurse -Force | ForEach-Object { $_.LastWriteTimeUtc = $old }
        (Get-Item -LiteralPath (Split-Path -Parent $directory)).LastWriteTimeUtc = $old
    }
}
function Receipt($name, $time) {
    $exe = Join-Path $fixture "dist\$name\VisionShield\VisionShield.exe"
    @{ output_name=$name; exe_sha256=(Get-FileHash -LiteralPath $exe).Hash; passed=$true; verified_at_utc=$time } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $fixture "dist\.verified\$name.json") -Encoding UTF8
}
try {
    foreach ($name in @('windows-current','windows-rollback','windows-old','windows-new','windows-unsafe','windows-personal')) {
        Make-Package $name $name ($name -ne 'windows-new')
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $fixture 'dist\.verified') | Out-Null
    Receipt 'windows-current' ([DateTime]::UtcNow.ToString('o'))
    Receipt 'windows-rollback' ([DateTime]::UtcNow.AddHours(-2).ToString('o'))
    $personal = Join-Path $fixture 'dist\windows-personal\VisionShield\private'
    New-Item -ItemType Directory -Path $personal | Out-Null
    Set-Content -LiteralPath (Join-Path $personal 'owner_templates.npz') -Value 'fictional private data'
    Get-ChildItem -LiteralPath (Join-Path $fixture 'dist\windows-personal') -Recurse -Force | ForEach-Object { $_.LastWriteTimeUtc = $old }
    (Get-Item -LiteralPath (Join-Path $fixture 'dist\windows-personal')).LastWriteTimeUtc = $old
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    foreach ($pair in @(@('VisionShield-Windows-current.zip','windows-current'),@('VisionShield-Windows-old.zip','windows-old'))) {
        $archivePath = Join-Path $fixture ('dist\' + $pair[0])
        $archive = [IO.Compression.ZipFile]::Open($archivePath, [IO.Compression.ZipArchiveMode]::Create)
        try {
            [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, (Join-Path $fixture "dist\$($pair[1])\VisionShield\VisionShield.exe"), 'VisionShield/VisionShield.exe') | Out-Null
        } finally { $archive.Dispose() }
        (Get-Item -LiteralPath $archivePath).LastWriteTimeUtc = $old
    }
    $userData = Join-Path $fixture 'private'
    New-Item -ItemType Directory -Path $userData | Out-Null
    Set-Content -LiteralPath (Join-Path $userData 'keep.txt') -Value 'fictional identity data'
    $link = Join-Path $fixture 'dist\windows-unsafe\linked-data'
    New-Item -ItemType Junction -Path $link -Target $userData | Out-Null
    (Get-Item -LiteralPath (Join-Path $fixture 'dist\windows-unsafe')).LastWriteTimeUtc = $old
    $script = Join-Path $fixture 'packaging\Clean-Artifacts.ps1'
    $preview = & $script -CurrentOutput 'windows-current' | ConvertFrom-Json
    if (@($preview.candidates).Count -ne 2 -or -not (Test-Path -LiteralPath (Join-Path $fixture 'dist\windows-old'))) { throw 'Preview/retention failed.' }
    $result = & $script -CurrentOutput 'windows-current' -Apply | ConvertFrom-Json
    if (Test-Path -LiteralPath (Join-Path $fixture 'dist\windows-old')) { throw 'Old artifact was not removed.' }
    if ((Test-Path -LiteralPath (Join-Path $fixture 'dist\VisionShield-Windows-old.zip')) -or
        -not (Test-Path -LiteralPath (Join-Path $fixture 'dist\VisionShield-Windows-current.zip'))) { throw 'Zip retention failed.' }
    foreach ($name in @('windows-current','windows-rollback','windows-new','windows-unsafe','windows-personal')) {
        if (-not (Test-Path -LiteralPath (Join-Path $fixture "dist\$name"))) { throw "Protected artifact removed: $name" }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $userData 'keep.txt'))) { throw 'User data touched.' }
    Set-Content -LiteralPath (Join-Path $fixture 'dist\windows-current\VisionShield\VisionShield.exe') -Value 'changed after verification'
    $rejected = $false
    try { & $script -CurrentOutput 'windows-current' -Apply | Out-Null } catch { $rejected = $true }
    if (-not $rejected) { throw 'Changed verified executable accepted.' }
    Write-Output 'Cleanup safety tests passed: preview, age, current/rollback retention, junction exclusion, private data, changed hash rejection.'
} finally {
    # Explicitly named temporary fixture; remove junction itself before recursive removal.
    if ([IO.Path]::GetDirectoryName($fixture) -ne [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') -or
        [IO.Path]::GetFileName($fixture) -notlike 'VisionShield-cleanup-test-*') { throw 'Unsafe fixture cleanup target.' }
    $junction = Join-Path $fixture 'dist\windows-unsafe\linked-data'
    if (Test-Path -LiteralPath $junction) { [IO.Directory]::Delete($junction) }
    Remove-Item -LiteralPath $fixture -Recurse -Force
}
