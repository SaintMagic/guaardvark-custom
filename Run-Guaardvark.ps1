$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Convert-ToWslPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$WindowsPath
    )

    $full = [System.IO.Path]::GetFullPath($WindowsPath)
    $drive = $full.Substring(0, 1).ToLowerInvariant()
    $rest = $full.Substring(2).Replace('\', '/')
    return "/mnt/$drive$rest"
}

function Get-WslDistros {
    try {
        $distros = & wsl.exe -l -q 2>$null
        if ($LASTEXITCODE -ne 0) {
            return @()
        }
        return @($distros | Where-Object { $_ -and $_.Trim() } | ForEach-Object { $_.Trim() })
    } catch {
        return @()
    }
}

function Get-WslPythonCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Distro
    )

    $probe = @'
if command -v python3.12 >/dev/null 2>&1; then
    printf '%s\n' "python3.12"
elif [ -x "$HOME/.local/bin/uv" ]; then
    "$HOME/.local/bin/uv" python find 3.12 2>/dev/null
fi
'@

    try {
        $result = & wsl.exe -d $Distro "bash" "-lc" $probe
        if ($LASTEXITCODE -ne 0) {
            return $null
        }
        $pythonCmd = @($result | Where-Object { $_ -and $_.Trim() } | Select-Object -First 1)
        if ($pythonCmd.Count -gt 0) {
            return $pythonCmd[0].Trim()
        }
        return $null
    } catch {
        return $null
    }
}

function Ensure-WslInstalled {
    $distros = Get-WslDistros
    if ($distros.Count -gt 0) {
        return $distros
    }

    if (-not (Test-IsAdmin)) {
        Start-Process powershell.exe -Verb RunAs -ArgumentList @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", $PSCommandPath
        ) | Out-Null
        exit 0
    }

    Write-Host "WSL is not ready on this machine. Starting WSL + Ubuntu install..." -ForegroundColor Yellow
    & wsl.exe --install -d Ubuntu

    if ($LASTEXITCODE -ne 0) {
        throw "WSL installation failed. Run 'wsl --install -d Ubuntu' manually in an elevated terminal."
    }

    Write-Host ""
    Write-Host "WSL installation has been started." -ForegroundColor Green
    Write-Host "If Windows asks for a reboot or Ubuntu first-run setup, finish that once and then run this launcher again." -ForegroundColor Green
    exit 0
}

$repoRoot = Split-Path -Parent $PSCommandPath
$wslRepoRoot = Convert-ToWslPath -WindowsPath $repoRoot
$distros = Ensure-WslInstalled
$distro = if ($distros -contains "Ubuntu") { "Ubuntu" } else { $distros[0] }
$pythonCmd = Get-WslPythonCommand -Distro $distro

if (-not $pythonCmd) {
    throw "Python 3.12 is not available in WSL distro '$distro'. Install python3.12 or run 'uv python install 3.12' inside WSL, then run this launcher again."
}

$linuxCommand = "cd '$wslRepoRoot' && export PYTHON_CMD='$pythonCmd' && bash ./scripts/wsl_prepare_backend_venv.sh && bash ./launch_guaardvark.sh services --no-tail"

Write-Host "Launching Guaardvark in WSL distro '$distro' from $wslRepoRoot using $pythonCmd" -ForegroundColor Cyan
Start-Process wsl.exe -ArgumentList @(
    "-d", $distro,
    "bash", "-lc", $linuxCommand
) | Out-Null
