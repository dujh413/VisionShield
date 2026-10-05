param([string]$Python, [switch]$Repair)
$ErrorActionPreference = 'Stop'
$module = Get-ChildItem -LiteralPath $PSScriptRoot -Directory |
    Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'desktop_guard.py') } |
    Select-Object -First 1
if (-not $module) { throw 'Desktop module was not found.' }
if (-not $Python) {
    $Python = Join-Path $module.FullName '.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $Python)) { throw 'Prepare the desktop virtual environment first.' }
# Never replace a system-wide Python runtime. CPU benchmark environments can
# remain separate while this application virtual environment loads DirectML.
& $Python -c 'import sys; sys.exit(0 if sys.prefix != sys.base_prefix else 3)'
if ($LASTEXITCODE -ne 0) { throw 'Use a dedicated virtual environment, not system Python.' }
@'
import sys
try:
    import onnxruntime as ort
    enabled = ort.__version__ == '1.24.4' and 'DmlExecutionProvider' in ort.get_available_providers()
except ImportError:
    enabled = False
sys.exit(0 if enabled else 2)
'@ | & $Python -
if ($Repair -or $LASTEXITCODE -ne 0) {
    & $Python -m pip install --disable-pip-version-check --force-reinstall --no-deps --index-url https://pypi.org/simple onnxruntime-directml==1.24.4
    if ($LASTEXITCODE -ne 0) { throw 'DirectML runtime installation failed.' }
}
@'
import onnxruntime as ort
print(ort.__version__, ort.get_available_providers())
assert 'DmlExecutionProvider' in ort.get_available_providers(), 'DirectML was not loaded'
'@ | & $Python -
if ($LASTEXITCODE -ne 0) { throw 'Loaded runtime has no DirectML provider.' }
$check = Join-Path $module.FullName 'gpu_ocr_check.py'
& $Python $check
if ($LASTEXITCODE -ne 0) { throw 'Actual GPU OCR verification failed.' }
Write-Output 'GPU OCR is enabled and verified in the selected application environment.'
