# One-line install of Vectiq on Windows 10/11, in PowerShell:
#
#   irm https://raw.githubusercontent.com/lucky-edgelord/aio-vector-bot/main/get.ps1 | iex
#
# It gets Git if it's missing (winget), puts Vectiq in %USERPROFILE%\vectiq (or $env:VECTIQ_DIR), and runs its
# installer, which asks for the bot's key and sets everything up. Options, as environment variables:
#
#   $env:VECTIQ_NO_SERVICE = "1"     install only; start it with ~\vectiq\run.ps1
#   $env:VECTIQ_YES = "1"            no questions (reads VECTOR_NSEC / VECTIQ_INVITE_URLS); for scripts and AI agents
#
# Run it again to update: it pulls the latest Vectiq and re-runs the installer, keeping your config and data.
& {
    $ErrorActionPreference = "Stop"
    $repo = if ($env:VECTIQ_REPO) { $env:VECTIQ_REPO } else { "https://github.com/lucky-edgelord/aio-vector-bot" }
    $dir = if ($env:VECTIQ_DIR) { $env:VECTIQ_DIR } else { Join-Path $env:USERPROFILE "vectiq" }
    function Say($m) { Write-Host "`n==> $m" -ForegroundColor Green }
    function Die($m) { Write-Host "xx $m" -ForegroundColor Red; throw $m }
    function Refresh-Path { $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User") }

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { Die "Install Git (https://git-scm.com) or 'App Installer' from the Microsoft Store, then run this again." }
        Say "Installing Git"
        winget install --id Git.Git -e --silent --accept-package-agreements --accept-source-agreements | Out-Null
        Refresh-Path
    }
    if (Test-Path (Join-Path $dir ".git")) {
        Say "Updating Vectiq in $dir"
        git -C $dir pull --ff-only -q
        if ($LASTEXITCODE -ne 0) { Die "Couldn't update $dir (local changes?). Fix it, or set `$env:VECTIQ_DIR to install elsewhere." }
    } elseif ((Test-Path $dir) -and (Get-ChildItem $dir -Force | Select-Object -First 1)) {
        Die "$dir exists and isn't a Vectiq checkout. Set `$env:VECTIQ_DIR to another folder."
    } else {
        Say "Downloading Vectiq to $dir"
        git clone -q --depth 1 $repo $dir
        if ($LASTEXITCODE -ne 0) { Die "Couldn't download Vectiq from $repo." }
    }
    $installArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $dir "install.ps1"))
    if ($env:VECTIQ_NO_SERVICE) { $installArgs += "-NoService" }
    if ($env:VECTIQ_YES) { $installArgs += "-Yes" }
    & powershell @installArgs
}
