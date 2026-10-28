param([switch]$SkipFetch)
$ErrorActionPreference = 'Continue'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$env:PYTHONPATH = $root
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$receiptDir = Join-Path $root 'work\receipts'
New-Item -ItemType Directory -Path $receiptDir -Force | Out-Null
$checks = [ordered]@{}
$script:failed = 0
function Run([string]$label, [string]$program, [string[]]$arguments) {
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $out = (& $program @arguments 2>&1 | Out-String)
    $code = $LASTEXITCODE
    $watch.Stop()
    $checks[$label] = [ordered]@{exit=$code;seconds=[math]::Round($watch.Elapsed.TotalSeconds,2);output=$out.Trim()}
    Write-Host ("[{0}] exit={1} {2}s" -f $label,$code,$checks[$label].seconds)
    if ($code -ne 0) { $script:failed++; Write-Host $out }
}
$bash = 'C:\Program Files\Git\bin\bash.exe'
if (-not $SkipFetch) { Run 'pinned_inputs' $bash @('fetch_inputs.sh') }
Run 'compileall' 'python' @('-m','compileall','-q','chipxray','tests')
foreach ($test in (Get-ChildItem 'tests\test_*.py' | Sort-Object Name)) {
    Run $test.BaseName 'python' @($test.FullName)
}
foreach ($chip in @('esp32','esp32s3','esp32c3','esp32c5','esp32c61')) {
    Run "baseline_$chip" 'python' @('-m','chipxray.baseline',"facts/${chip}_librftest.json","blobs/svd/${chip}.svd")
}
$digests = [ordered]@{}
if (Test-Path 'blobs') {
    Get-ChildItem 'blobs' -File -Recurse | Sort-Object FullName | ForEach-Object {
        $rel = $_.FullName.Substring($root.Length + 1).Replace('\','/')
        $digests[$rel] = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
$receipt = [ordered]@{
    timestamp_utc = $stamp
    hostname = $env:COMPUTERNAME
    repo = $root
    git_head = (git rev-parse HEAD).Trim()
    python = (python --version | Out-String).Trim()
    checks = $checks
    input_sha256 = $digests
    failure_count = $script:failed
}
$receiptPath = Join-Path $receiptDir "verification-$stamp.json"
$receipt | ConvertTo-Json -Depth 8 | Set-Content -Path $receiptPath -Encoding UTF8
Write-Host "RECEIPT=$receiptPath"
Write-Host "FAILURES=$script:failed"
if ($script:failed -ne 0) { exit 1 }
exit 0
