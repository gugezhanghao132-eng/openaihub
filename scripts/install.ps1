$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$InstallRoot = Join-Path $env:USERPROFILE '.openaihub'
$BinRoot = Join-Path $InstallRoot 'bin'
$ScriptPath = $PSCommandPath
if (-not $ScriptPath -and $MyInvocation -and $MyInvocation.MyCommand) {
  $ScriptPath = $MyInvocation.MyCommand.Path
}
$ScriptRoot = $null
$SourceRoot = $null
$SourcePackage = $null
$SourceDist = $null
$VersionFile = $null
if ($ScriptPath) {
  $ScriptRoot = Split-Path -Parent $ScriptPath
  $SourceRoot = Split-Path -Parent $ScriptRoot
  $SourcePackage = Join-Path $SourceRoot 'package'
  $SourceDist = Join-Path $SourceRoot 'dist\openaihub'
  $VersionFile = Join-Path $SourcePackage 'version.txt'
}
$AlreadyInstalled = Test-Path (Join-Path $BinRoot 'openaihub.exe')
$RepoOwner = 'gugezhanghao132-eng'
$RepoName = 'openaihub'
$AssetName = 'openaihub-windows.zip'
$LatestReleaseApi = "https://api.github.com/repos/$RepoOwner/$RepoName/releases/latest"

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
    $errorText = 'Install step failed.'
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

function Get-VersionText {
  param(
    [string]$Fallback = 'latest'
  )
  if ($VersionFile -and (Test-Path $VersionFile)) {
    return (Get-Content $VersionFile -Raw).Trim()
  }
  return $Fallback.TrimStart('v')
}

function Invoke-WithRetry {
  param(
    [scriptblock]$Action,
    [int]$MaxAttempts = 3,
    [int]$DelaySeconds = 2
  )

  $attempt = 0
  while ($true) {
    try {
      return & $Action
    } catch {
      $attempt++
      if ($attempt -ge $MaxAttempts) {
        throw
      }
      Start-Sleep -Seconds $DelaySeconds
    }
  }
}

$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('openaihub-install-' + [guid]::NewGuid().ToString('N'))
$PayloadRoot = Join-Path $TempRoot 'payload'
$PayloadBinRoot = Join-Path $PayloadRoot 'bin'
$StageBinRoot = Join-Path $TempRoot 'bin-stage'
$RemoteMode = $true
if ($SourceDist) {
  $RemoteMode = -not (Test-Path (Join-Path $SourceDist 'openaihub.exe'))
}
$VersionText = Get-VersionText

Invoke-WithSpinner -Message 'Preparing install directory...' -Action {
  New-Item -ItemType Directory -Force -Path $using:InstallRoot | Out-Null
  New-Item -ItemType Directory -Force -Path $using:TempRoot | Out-Null
  New-Item -ItemType Directory -Force -Path $using:PayloadRoot | Out-Null
  New-Item -ItemType Directory -Force -Path $using:StageBinRoot | Out-Null
}

if ($RemoteMode) {
  $ReleaseInfo = Invoke-WithRetry -Action {
    Invoke-RestMethod -Uri $LatestReleaseApi -Headers @{ 'User-Agent' = 'OpenAIHub-Installer' }
  }
  $VersionText = Get-VersionText -Fallback ([string]$ReleaseInfo.tag_name)
  $RemoteZipUrl = $null
  foreach ($asset in $ReleaseInfo.assets) {
    if ($asset.name -eq $AssetName) {
      $RemoteZipUrl = [string]$asset.browser_download_url
      break
    }
  }
  if (-not $RemoteZipUrl) {
    throw 'Latest release does not contain the Windows asset.'
  }
  $ZipPath = Join-Path $TempRoot $AssetName
  Invoke-WithSpinner -Message 'Downloading release package...' -Action {
    $attempt = 0
    while ($true) {
      try {
        Invoke-WebRequest -Uri $using:RemoteZipUrl -OutFile $using:ZipPath -UseBasicParsing
        break
      } catch {
        $attempt++
        if ($attempt -ge 3) {
          throw
        }
        Start-Sleep -Seconds 2
      }
    }
  }
  Invoke-WithSpinner -Message 'Extracting release package...' -Action {
    Expand-Archive -Path $using:ZipPath -DestinationPath $using:PayloadRoot -Force
  }
  $ExtractExe = Get-ChildItem -Path $PayloadRoot -Recurse -Filter 'openaihub.exe' | Select-Object -First 1
  if (-not $ExtractExe) {
    throw 'Downloaded package does not contain openaihub.exe'
  }
  $PayloadBinRoot = $ExtractExe.Directory.FullName
} else {
  $PayloadBinRoot = $SourceDist
}

Invoke-WithSpinner -Message 'Cleaning previous files...' -Action {
  $installRoot = $using:InstallRoot
  $installRootPrefix = $installRoot.TrimEnd('\\') + '\\'
  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
      $_.ExecutablePath -and $_.ExecutablePath.StartsWith($installRootPrefix, [System.StringComparison]::OrdinalIgnoreCase)
    } |
    ForEach-Object {
      Invoke-CimMethod -InputObject $_ -MethodName Terminate -ErrorAction SilentlyContinue | Out-Null
    }
  Start-Sleep -Milliseconds 300
  Remove-Item -Path $using:StageBinRoot -Recurse -Force -ErrorAction SilentlyContinue
  New-Item -ItemType Directory -Force -Path $using:StageBinRoot | Out-Null
  Remove-Item -Path (Join-Path $using:InstallRoot 'app') -Recurse -Force -ErrorAction SilentlyContinue
}

Invoke-WithSpinner -Message 'Copying bundled runtime...' -Action {
  $source = $using:PayloadBinRoot
  $destination = $using:StageBinRoot
  Get-ChildItem -Path $source -Recurse -Force | ForEach-Object {
    $relativePath = $_.FullName.Substring($source.Length).TrimStart('\\')
    $targetPath = Join-Path $destination $relativePath
    if ($_.PSIsContainer) {
      New-Item -ItemType Directory -Force -Path $targetPath | Out-Null
      return
    }

    $targetDir = Split-Path -Parent $targetPath
    if (-not (Test-Path $targetDir)) {
      New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
    }

    $attempt = 0
    while ($true) {
      try {
        [System.IO.File]::Copy($_.FullName, $targetPath, $true)
        break
      } catch {
        $attempt++
        if ($attempt -ge 10) {
          throw
        }
        Start-Sleep -Milliseconds 500
      }
    }
  }
}

Invoke-WithSpinner -Message 'Installing command aliases...' -Action {
  $aliasPath = Join-Path $using:StageBinRoot 'OAH.cmd'
  Set-Content -Path $aliasPath -Encoding ASCII -Value "@echo off`r`nsetlocal`r`nchcp 65001 >nul`r`n`"%~dp0openaihub.exe`" %*`r`n"
  Set-Content -Path (Join-Path $using:InstallRoot 'version.txt') -Value $using:VersionText -Encoding UTF8
}

Invoke-WithSpinner -Message 'Activating installed runtime...' -Action {
  $stageBinRoot = $using:StageBinRoot
  $liveBinRoot = $using:BinRoot
  $backupBinRoot = Join-Path $using:InstallRoot ('bin-backup-' + [guid]::NewGuid().ToString('N'))

  if (Test-Path $backupBinRoot) {
    Remove-Item -Path $backupBinRoot -Recurse -Force -ErrorAction SilentlyContinue
  }

  if (Test-Path $liveBinRoot) {
    Move-Item -Path $liveBinRoot -Destination $backupBinRoot -Force
  }

  Move-Item -Path $stageBinRoot -Destination $liveBinRoot -Force
  Remove-Item -Path $backupBinRoot -Recurse -Force -ErrorAction SilentlyContinue
}

Invoke-WithSpinner -Message 'Updating PATH...' -Action {
  $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
  if (-not $userPath) {
    $userPath = ''
  }
  if (($userPath -split ';') -notcontains $using:BinRoot) {
    $newPath = ($userPath.TrimEnd(';') + ';' + $using:BinRoot).Trim(';')
    [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
  }
}

Remove-Item -Path $TempRoot -Recurse -Force -ErrorAction SilentlyContinue

if ($AlreadyInstalled) {
  Write-Host 'OpenAI Hub update complete.'
} else {
  Write-Host 'OpenAI Hub install complete.'
}
Write-Host ('Install path: ' + $InstallRoot)
Write-Host ('Version: ' + (Get-Content (Join-Path $InstallRoot 'version.txt') -Raw).Trim())
Write-Host 'Reopen terminal, then use:'
Write-Host '  openaihub'
Write-Host '  OAH'
