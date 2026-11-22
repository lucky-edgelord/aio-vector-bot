# Vectiq installer for Windows 10/11 (PowerShell). Safe to re-run.
#
#   .\install.ps1                 interactive: asks for the bot's key, installs, starts it at logon
#   .\install.ps1 -NoService      install only; start it yourself with .\run.ps1
#   .\install.ps1 -Yes            no prompts (reads VECTOR_NSEC / VECTIQ_INVITE_URLS from the environment)
# If scripts are blocked:  powershell -ExecutionPolicy Bypass -File .\install.ps1
param([switch]$NoService, [switch]$Yes)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Root = (Get-Location).Path

function Say($m)  { Write-Host "`n==> $m" -ForegroundColor Green }
function Warn($m) { Write-Host "!! $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "xx $m" -ForegroundColor Red; exit 1 }
function Refresh-Path { $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User") + ";$env:USERPROFILE\.cargo\bin" }
function Have($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }

if (-not (Have winget)) { Die "winget is needed to install the tools (it ships with current Windows 10/11; install 'App Installer' from the Microsoft Store)." }
function Winget-Install($id, $label) {
    Say "Installing $label"
    winget install --id $id -e --silent --accept-package-agreements --accept-source-agreements | Out-Null
}

Refresh-Path
$py = $null
foreach ($c in @("py -3.12", "py -3", "python")) {
    try { $v = & cmd /c "$c -c ""import sys;print(sys.version_info>=(3,10))"" 2>nul"; if ($v -eq "True") { $py = $c; break } } catch {}
}
if (-not $py) { Winget-Install "Python.Python.3.12" "Python 3.12"; Refresh-Path; $py = "py -3.12" }
if (-not (Have git))   { Winget-Install "Git.Git" "Git"; Refresh-Path }
if (-not (Have cmake)) { Winget-Install "Kitware.CMake" "CMake"; Refresh-Path }
if (-not (Have cargo)) { Winget-Install "Rustlang.Rustup" "Rust"; Refresh-Path }
if (-not (Have ffmpeg)) { try { Winget-Install "Gyan.FFmpeg" "ffmpeg (music and talking videos)"; Refresh-Path } catch { Warn "Couldn't install ffmpeg; music and talking videos need it (winget install Gyan.FFmpeg)." } }
$hasMsvc = (Test-Path "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe") -and
    (& "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe" -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath)
if (-not $hasMsvc) {
    Say "Installing the Visual Studio C++ build tools (the Vector SDK compiles a Rust core; this is a big download)"
    winget install --id Microsoft.VisualStudio.2022.BuildTools -e --silent --accept-package-agreements --accept-source-agreements `
        --override "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended" | Out-Null
}
if (-not (Have cargo)) { Die "Rust isn't on PATH yet. Close this window, open a new PowerShell and run .\install.ps1 again." }

Say "Creating the virtual environment and installing Vectiq (the first build takes several minutes)"
if (-not (Test-Path .venv)) { & cmd /c "$py -m venv .venv"; if ($LASTEXITCODE) { Die "couldn't create the virtual environment" } }
$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
& $venvPy -m pip install -q --upgrade pip
& $venvPy -m pip install -q -e ".[webhooks,dashboard,music]"
if ($LASTEXITCODE) { Die "installing Vectiq failed (see the messages above)" }

function Set-EnvVar($k, $v) {
    $lines = if (Test-Path .env) { Get-Content .env } else { @() }
    $found = $false
    $out = foreach ($l in $lines) { if ($l -match "^$k=") { $found = $true; "$k=$v" } else { $l } }
    if (-not $found) { $out = @($out) + "$k=$v" }
    Set-Content -Path .env -Value $out -Encoding ascii
}
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
$hasKey = Select-String -Path .env -Pattern '^VECTOR_NSEC=nsec1[0-9a-z]{20,}' -Quiet
$hasInv = Select-String -Path .env -Pattern '^VECTIQ_INVITE_URLS=.{10,}' -Quiet
$nsec = $env:VECTOR_NSEC; $inv = $env:VECTIQ_INVITE_URLS
if (-not $Yes) {
    if (-not $hasKey -and -not $nsec) { $nsec = Read-Host "The bot's Vector key (nsec1..., blank to generate a new one)" }
    if (-not $hasInv -and -not $inv) { $inv = Read-Host "Community invite link(s) to join, space-separated (blank to skip)" }
}
if (-not $hasKey -and -not $nsec) {
    $nsec = (& $venvPy -c "import vector; print(vector.generate_nsec())").Trim()
    Say "Generated a new Vector identity (saved in .env; back it up, it is the bot's account)"
}
if ($nsec) { Set-EnvVar "VECTOR_NSEC" $nsec }
if ($inv)  { Set-EnvVar "VECTIQ_INVITE_URLS" $inv }
# keep .env private to this user
icacls .env /inheritance:r /grant:r "${env:USERNAME}:(R,W)" | Out-Null

if (-not $Yes) {
    $wiz = Read-Host "Run the setup wizard now? It asks about features, channels and verification. [Y/n]"
    if ($wiz -notmatch '^[Nn]') { & $venvPy -m vectiq --setup }
}

Say "Checking config.yaml"
& $venvPy -m vectiq --check
if ($LASTEXITCODE) { Die "config.yaml has a problem (see above)" }

if (-not $NoService) {
    New-Item -ItemType Directory -Force data | Out-Null
    $cmd = "Set-Location '$Root'; & '$venvPy' -m vectiq *>> data\vectiq.log"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -Command `"$cmd`"" -WorkingDirectory $Root
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName Vectiq -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Start-ScheduledTask -TaskName Vectiq
    Say "Vectiq is running and will start when you log in. Logs: $Root\data\vectiq.log"
} else {
    Say "Installed. Start it with .\run.ps1"
}

Write-Host @"

Next steps
  1. In your Vector community, give the bot's account a role with the permissions it needs
     (Manage Roles, Manage Channels, Manage Messages, Moderate Members, Kick/Ban as you like).
  2. Edit config.yaml and restart: Stop-ScheduledTask Vectiq; Start-ScheduledTask Vectiq   (or .\run.ps1)
  3. Type !help in any channel.
"@
