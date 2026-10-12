param(
    [Parameter(Mandatory)][string]$Fw,
    [string]$Markers = "lamp or wifi",
    [string]$Port = "COM4"
)

Set-Location $PSScriptRoot
$date = Get-Date -Format "yyyyMMdd"
$dir = ".\logs\automated\lamp\$Fw"
New-Item -ItemType Directory -Force $dir | Out-Null

& .\.venv\Scripts\python.exe -m pytest -c pytest.ini -s -m $Markers `
    --port $Port --expected-fw-version $Fw `
    -o log_cli=true -o log_cli_level=DEBUG `
    --log-file="$dir\run-$date-full.log" --log-file-level=DEBUG `
    --junitxml="$dir\run-$date-junit.xml" -rA
