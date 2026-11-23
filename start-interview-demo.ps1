param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 19073
)

$ErrorActionPreference = 'Stop'
$demoPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $demoPython -PathType Leaf)) {
    throw 'Python environment missing. Run uv sync --locked in the project directory first.'
}

Write-Host "Work Observer interview demo: http://127.0.0.1:$Port"
Write-Host 'Synthetic examples and scripted replies. Local experiments execute real calculations.'
Write-Host 'No credentials, recruitment crawling, or external model calls. Ctrl+C stops the demo.'
Push-Location -LiteralPath $PSScriptRoot
try {
    & $demoPython -X utf8 -c 'from work_observer.cli import app; app()' serve --demo --port $Port
    if ($LASTEXITCODE -ne 0) {
        throw "Demo exited with code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
