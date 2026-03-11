param(
    [Parameter(Mandatory = $true)]
    [string]$OpenClawCmd,

    [string]$GatewayLauncher = ""
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = "SilentlyContinue"

if (-not (Test-Path $OpenClawCmd)) {
    exit 1
}

& $OpenClawCmd gateway stop 2>&1 | Out-Null
Start-Sleep -Seconds 2

if ($GatewayLauncher) {
    $targets = Get-CimInstance Win32_Process | Where-Object {
        $_.Name -ieq 'cmd.exe' -and $_.CommandLine -like ('*' + $GatewayLauncher + '*')
    }
    foreach ($proc in $targets) {
        try {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
        } catch {}
    }
    Start-Sleep -Seconds 1
}

$portCheck = netstat -ano | Select-String ":18789.*LISTENING"
if ($portCheck) {
    foreach ($line in $portCheck) {
        $parts = $line.ToString().Trim() -split '\s+'
        $procId = $parts[-1]
        if ($procId -and $procId -ne "0") {
            taskkill /PID $procId /F 2>$null | Out-Null
        }
    }
    Start-Sleep -Seconds 2
}

& $OpenClawCmd gateway start 2>&1 | Out-Null
