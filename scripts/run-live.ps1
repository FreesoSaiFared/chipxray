param(
    [string]$Chip = 'esp32c5',
    [switch]$Strip,
    [ValidateRange(1,12)][int]$Budget = 8,
    [ValidateSet('agent','oneshot')][string]$Mode = 'agent',
    [ValidateRange(1,50)][int]$Top = 30,
    [string]$Model = 'openai/gpt-4.1-mini'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
if (-not $env:OPENROUTER_API_KEY) { throw 'Missing OpenRouter configuration' }
$env:PYTHONPATH = $root
$env:CHIPXRAY_LLM_BASE_URL = 'https://openrouter.ai/api/v1'
$env:CHIPXRAY_LLM_MODEL = $Model
$env:CHIPXRAY_LLM_API_KEY = $env:OPENROUTER_API_KEY
$ts = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$log = Join-Path $root "work\receipts\live-$Mode-$Chip-$ts.log"
$params = @('-m',"chipxray.$Mode",$Chip)
if ($Mode -eq 'agent') { $params += @('--budget',"$Budget") }
else { $params += @('--top',"$Top") }
if ($Strip) { $params += '--strip' }
Write-Host "MODEL=$Model CHIP=$Chip STRIPPED=$Strip MODE=$Mode BUDGET=$Budget TOP=$Top"
& python @params 2>&1 | Tee-Object -FilePath $log
$rc = $LASTEXITCODE
Remove-Item Env:\CHIPXRAY_LLM_API_KEY -ErrorAction SilentlyContinue
Write-Host "LIVE_EXIT=$rc LOG=$log"
exit $rc
