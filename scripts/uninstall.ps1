$ErrorActionPreference = 'Stop'

$InstallRoot = Join-Path $env:USERPROFILE '.openaihub'
$BinRoot = Join-Path $InstallRoot 'bin'

function Invoke-WithSpinner {
  param(
    [string]$Message,
    [scriptblock]$Action
  )

  $frames = @('|', '/', '-', '\')
  $job = Start-Job -ScriptBlock $Action
  $index = 0
  while ($job.State -eq 'Running' -or $job.State -eq 'NotStarted') {
    $frame = $frames[$index % $frames.Count]
    Write-Host -NoNewline ("`r[{0}] {1}" -f $frame, $Message)
    Start-Sleep -Milliseconds 120
    $index++
    $job = Get-Job -Id $job.Id
  }

  Receive-Job -Job $job -Wait | Out-Null
  if ($job.State -ne 'Completed') {
    $errorText = 'Uninstall step failed.'
    if ($job.ChildJobs.Count -gt 0 -and $job.ChildJobs[0].JobStateInfo.Reason) {
      $errorText = $job.ChildJobs[0].JobStateInfo.Reason.Message
    }
    Remove-Job -Job $job -Force | Out-Null
    Write-Host -NoNewline ("`r[x] {0}" -f $Message)
    Write-Host
    throw $errorText
  }

  Remove-Job -Job $job -Force | Out-Null
  Write-Host -NoNewline ("`r[ok] {0}" -f $Message)
  Write-Host
}

Invoke-WithSpinner -Message 'Updating PATH...' -Action {
  $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
  if ($userPath) {
    $parts = @($userPath -split ';' | Where-Object { $_ -and ($_ -ne $using:BinRoot) })
    [Environment]::SetEnvironmentVariable('Path', ($parts -join ';'), 'User')
  }
}

Invoke-WithSpinner -Message 'Removing installed files...' -Action {
  Remove-Item -Path $using:InstallRoot -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host 'OpenAI Hub uninstall complete.'
Write-Host ('Removed path: ' + $InstallRoot)
