$ErrorActionPreference = 'Stop'

$InstallRoot = Join-Path $env:USERPROFILE '.openaihub'
$BinRoot = Join-Path $InstallRoot 'bin'
$RuntimeRoot = Join-Path $InstallRoot 'npm-runtime'

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

Write-Host 'OpenAI Hub uninstall complete.'
Write-Host 'Command aliases removed from PATH.'
if (Test-Path $RuntimeRoot) {
  Remove-Item -Path $RuntimeRoot -Recurse -Force
  Write-Host ('Removed runtime files at: ' + $RuntimeRoot)
}
Write-Host ('User data preserved at: ' + $InstallRoot)
Write-Host 'If you want to fully remove saved accounts and config, delete that folder manually.'
