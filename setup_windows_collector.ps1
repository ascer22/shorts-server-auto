# Windows 10/11 setup for a local-only YouTube Shorts MP4 collector.
# Downloads only from @i11ush, @keymood_yt, @world_edges. NEVER posts to TikTok.
# Run from PowerShell in the project folder:
# powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_windows_collector.ps1
param(
    [ValidateSet("none", "edge", "chrome", "firefox")]
    [string]$Browser = "none",
    [string]$At = "11:30"
)

$ErrorActionPreference = "Stop"
$Project = Split-Path -Parent $MyInvocation.MyCommand.Path
$Collector = Join-Path $Project "windows_short_collector.py"
$TaskName = "Shorts MP4 Collector (Approved Channels Only)"

if (-not (Test-Path -LiteralPath $Collector)) {
    throw "Cannot find windows_short_collector.py in the same folder."
}
if ($At -notmatch '^(?:[01][0-9]|2[0-3]):[0-5][0-9]$') {
    throw "Expected 24-hour time, for example -At 11:30"
}

# Prefer Python's Windows Launcher, but use the python executable if needed.
$Python = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    $candidate = & py -3 -c "import sys; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $candidate) {
        $Python = ($candidate | Select-Object -First 1).Trim()
    }
}
if (-not $Python -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $candidate = & python -c "import sys; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $candidate) {
        $Python = ($candidate | Select-Object -First 1).Trim()
    }
}
if (-not $Python -or -not (Test-Path -LiteralPath $Python)) {
    throw "Python is not installed. Install Python 3.11+ and enable Add Python to PATH, then rerun this setup."
}

Write-Host "Python found. Installing/updating yt-dlp..."
& $Python -m pip install --disable-pip-version-check --upgrade yt-dlp
if ($LASTEXITCODE -ne 0) {
    throw "yt-dlp installation failed. Review pip output above."
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue) -or
    -not (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
    Write-Warning "FFmpeg is required for MP4 conversion and mirroring."
    Write-Host "To install with Windows Package Manager:"
    Write-Host "  winget install --id Gyan.FFmpeg -e"
    Write-Host "After installation, RESTART PowerShell and rerun this setup."
    exit 2
}

# Task Scheduler runs as the signed-in user, so browser session access remains
# local to their Windows profile. Do NOT run as SYSTEM or upload cookies to GitHub.
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$trigger = New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.Add([TimeSpan]::Parse($At)))
$argument = '"' + $Collector + '" --browser ' + $Browser + ' --max-downloads 1'
$action = New-ScheduledTaskAction -Execute $Python -Argument $argument -WorkingDirectory $Project
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null

Write-Host ""
Write-Host "Scheduled task installed: $TaskName"
Write-Host "Daily time: $At (your Windows local time)."
Write-Host "Source channels: @i11ush, @keymood_yt, @world_edges."
Write-Host "Browser mode: $Browser (login session stays on your PC)."
Write-Host "Files: $Project\local_downloads\@channel\VIDEO_ID.mp4"
Write-Host "Log:   $Project\local_downloads\collector.log"
Write-Host "This task requires your PC to be ON and your Windows user logged in."
Write-Host "No media is sent to Cloudinary, Buffer, or TikTok by this collector."
Write-Host ""
Write-Host "Test the download manually:"
Write-Host ('  & "' + $Python + '" "' + $Collector + '" --browser ' + $Browser)
