param(
    [Parameter(Mandatory=$true)][string]$Repository,
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][string]$SourceArchiveDirectory,
    [string]$Version = '0.1.0-preview.1'
)
$ErrorActionPreference = 'Stop'
if ($Version -notmatch '^\d+\.\d+\.\d+(?:-(?:preview|alpha|beta)\.\d+)?$') { throw 'Use a semantic version.' }
$Repository = (Resolve-Path -LiteralPath $Repository).Path
$output = 'windows-public-' + $Version.Replace('.', '-')
& (Join-Path $Repository 'packaging\Build.ps1') -Python $Python -OutputName $output
& $Python (Join-Path $PSScriptRoot 'package_public.py') --repository $Repository --output-name $output --version $Version --source-archives $SourceArchiveDirectory
if ($LASTEXITCODE -ne 0) { throw 'Public package preparation failed.' }
