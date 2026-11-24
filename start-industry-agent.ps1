param(
    [ValidateRange(1024,65535)]
    [int]$Port=19076,
    [string]$DataDirectory='data/reader-answer-preview'
)
$ErrorActionPreference='Stop'
$agentPython=Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
$agentDataPath=if([IO.Path]::IsPathRooted($DataDirectory)){$DataDirectory}else{Join-Path $PSScriptRoot $DataDirectory}
$agentDatabase=Join-Path $agentDataPath 'app.db'
if(-not(Test-Path -LiteralPath $agentPython -PathType Leaf)){throw 'Project Python environment is missing.'}
if(-not(Test-Path -LiteralPath $agentDatabase -PathType Leaf)){throw 'The requested working database does not exist. Specify an existing data directory.'}
$agentOverrides=@{
    WO_DATABASE_PATH=$agentDatabase
    WO_RAW_DIRECTORY=(Join-Path $agentDataPath 'raw')
    WO_MCP_CONFIG=(Join-Path $agentDataPath 'no-mcp.toml')
}
$agentPrior=@{}
foreach($agentName in $agentOverrides.Keys){
    $agentPrior[$agentName]=[Environment]::GetEnvironmentVariable($agentName,'Process')
    [Environment]::SetEnvironmentVariable($agentName,$agentOverrides[$agentName],'Process')
}
Write-Host "Work Observer Agent: http://127.0.0.1:$Port"
Write-Host 'Uses the configured model and existing archived job data. No recruitment crawling starts.'
Push-Location -LiteralPath $PSScriptRoot
try {
    & $agentPython -X utf8 -c 'from work_observer.cli import app; app()' serve --port $Port --db $agentDatabase --reports-dir (Join-Path $agentDataPath 'reports') --env-file (Join-Path $PSScriptRoot '.env')
    if($LASTEXITCODE -ne 0){throw "Agent exited with code $LASTEXITCODE."}
}
finally {
    Pop-Location
    foreach($agentName in $agentOverrides.Keys){[Environment]::SetEnvironmentVariable($agentName,$agentPrior[$agentName],'Process')}
}
