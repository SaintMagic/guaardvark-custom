$ErrorActionPreference = "Stop"
if ($null -ne (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue)) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$repoRoot = Split-Path -Parent $PSCommandPath
$venvDir = Join-Path $repoRoot ".launcher-venv"
$venvPython = Join-Path $venvDir "Scripts\pythonw.exe"
$venvPythonCli = Join-Path $venvDir "Scripts\python.exe"
$launcherScript = Join-Path $repoRoot "GuaardvarkLauncher.pyw"
$requiredModules = @(
    @{ Package = "PyQt6"; Import = "PyQt6" },
    @{ Package = "PyQt6-WebEngine"; Import = "PyQt6.QtWebEngineWidgets" }
)

function Get-PythonCommand {
    $candidates = @(
        @{ Exe = "py"; Args = @("-3.12") },
        @{ Exe = "python"; Args = @() }
    )
    foreach ($candidate in $candidates) {
        try {
            & $candidate.Exe @($candidate.Args + @("-c", "print('ok')")) 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) {
                return $candidate
            }
        } catch {
            continue
        }
    }
    throw "Python 3.12 was not found on PATH."
}

function Invoke-PythonCommand {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$PythonCommand,
        [Parameter(Mandatory = $true)]
        [string[]]$Args
    )
    & $PythonCommand.Exe @($PythonCommand.Args + $Args)
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed: $($PythonCommand.Exe) $($PythonCommand.Args -join ' ') $($Args -join ' ')"
    }
}

function Ensure-LauncherVenv {
    if (Test-Path $venvPythonCli) {
        return
    }
    $pythonCmd = Get-PythonCommand
    Write-Host "Creating launcher venv..." -ForegroundColor Cyan
    Invoke-PythonCommand -PythonCommand $pythonCmd -Args @("-m", "venv", $venvDir)
}

function Test-ModuleInstalled {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ModuleName
    )
    if (-not (Test-Path $venvPythonCli)) {
        return $false
    }
    try {
        & $venvPythonCli -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('$ModuleName') else 1)" 2>&1 | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Ensure-LauncherDeps {
    $missing = @()
    foreach ($module in $requiredModules) {
        if (-not (Test-ModuleInstalled -ModuleName $module.Import)) {
            $missing += $module.Package
        }
    }
    if ($missing.Count -eq 0) {
        return
    }

    Write-Host "Installing launcher GUI dependencies..." -ForegroundColor Cyan
    & $venvPythonCli -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to upgrade pip in launcher venv."
    }
    & $venvPythonCli -m pip install @missing
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install launcher dependencies: $($missing -join ', ')"
    }
}

Ensure-LauncherVenv
Ensure-LauncherDeps

Write-Host "Launching Guaardvark GUI..." -ForegroundColor Green
Start-Process -FilePath $venvPython -WorkingDirectory $repoRoot -ArgumentList @($launcherScript) | Out-Null
