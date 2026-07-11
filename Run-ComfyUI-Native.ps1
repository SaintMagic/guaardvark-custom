$ErrorActionPreference = "Stop"
if ($null -ne (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue)) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$repoRoot = Split-Path -Parent $PSCommandPath
$comfyDir = Join-Path $repoRoot "plugins\comfyui\ComfyUI"
$venvDir = Join-Path $repoRoot "plugins\comfyui\.venv-windows"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$envFile = Join-Path $repoRoot ".env"
$defaultPort = 8191
$defaultFlags = @("--reserve-vram", "0.3")
$torchIndexUrl = "https://download.pytorch.org/whl/cu128"

function Get-PythonCommand {
    $candidates = @(
        @{ Exe = "py"; Args = @("-3.12") },
        @{ Exe = "py"; Args = @("-3") },
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
    throw "Python 3 was not found on PATH."
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

function Test-CommandExists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-PipInstallCode {
    @'
from importlib import metadata
from packaging.requirements import Requirement
import sys

args = sys.argv[1:]
for raw in args:
    req = Requirement(raw)
    try:
        installed = metadata.version(req.name)
    except metadata.PackageNotFoundError:
        sys.exit(1)
    if req.specifier and installed not in req.specifier:
        sys.exit(1)
sys.exit(0)
'@
}

function Test-PipPackagesInstalled {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Packages
    )
    if (-not (Test-Path $venvPython)) {
        return $false
    }
    $script = Get-PipInstallCode
    try {
        $output = & $venvPython -c $script @Packages 2>&1
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Test-TorchCuda {
    $script = @'
import torch
print(torch.__version__)
print("cuda=" + str(torch.cuda.is_available()))
'@
    try {
        $output = & $venvPython -c $script 2>$null
        return ($LASTEXITCODE -eq 0 -and ($output -join "`n") -match "cuda=True")
    } catch {
        return $false
    }
}

function Ensure-PipBase {
    if (-not (Test-PipPackagesInstalled -Packages @("pip", "wheel", "setuptools", "packaging"))) {
        Write-Host "Upgrading base packaging tools..." -ForegroundColor Cyan
        Invoke-Pip -Args @("install", "--upgrade", "pip", "wheel", "setuptools", "packaging")
    }
}

function Ensure-TorchCuda {
    if (Test-TorchCuda) {
        Write-Host "CUDA-enabled torch is already installed in the Windows ComfyUI venv." -ForegroundColor DarkGreen
        return
    }

    Write-Host "Installing CUDA-enabled PyTorch from $torchIndexUrl..." -ForegroundColor Cyan
    Invoke-Pip -Args @(
        "install",
        "--upgrade",
        "--index-url", $torchIndexUrl,
        "torch",
        "torchvision",
        "torchaudio"
    )
}

function Ensure-PythonDeps {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RequirementsFile,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )
    if (Test-PipPackagesInstalled -Packages (Get-Content -Path $RequirementsFile | Where-Object { $_ -and -not $_.StartsWith("#") })) {
        Write-Host "$Label requirements already satisfied." -ForegroundColor DarkGreen
        return
    }
    Write-Host "Installing $Label requirements..." -ForegroundColor Cyan
    Invoke-Pip -Args @("install", "-r", $RequirementsFile)
}

function Ensure-VideoExtras {
    $packages = @(
        "numpy>=2",
        "opencv-python>=5.0.0.93",
        "gguf>=0.13.0",
        "sentencepiece",
        "protobuf",
        "imageio-ffmpeg",
        "websocket-client==1.8.0"
    )
    if (Test-PipPackagesInstalled -Packages $packages) {
        Write-Host "Video-critical extras already satisfied." -ForegroundColor DarkGreen
        return
    }
    Write-Host "Installing video-critical extras..." -ForegroundColor Cyan
    Invoke-Pip -Args (@("install") + $packages)
}

function Ensure-OptionalFlashAttention {
    if ($env:GUAARDVARK_ENABLE_FLASH_ATTN -notin @("1", "true", "TRUE", "True")) {
        return
    }
    if (Test-PipPackagesInstalled -Packages @("flash-attn")) {
        Write-Host "flash-attn already present." -ForegroundColor DarkGreen
        return
    }
    if (-not (Test-CommandExists -Name "cl")) {
        Write-Warning "Skipping flash-attn: Visual Studio C++ build tools are not available."
        return
    }
    Write-Warning "flash-attn installation on Windows is experimental. Skipping automatic install unless you explicitly want to force it."
}

function Get-ComfyPort {
    if (-not (Test-Path $envFile)) { return $defaultPort }
    $match = Select-String -Path $envFile -Pattern '^GUAARDVARK_COMFYUI_URL=http://127\.0\.0\.1:(\d+)$' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($match -and $match.Matches.Count -gt 0) {
        return [int]$match.Matches[0].Groups[1].Value
    }
    return $defaultPort
}

function Ensure-Venv {
    if (Test-Path $venvPython) { return }
    $pythonCmd = Get-PythonCommand
    Write-Host "Creating Windows ComfyUI venv at $venvDir" -ForegroundColor Cyan
    Invoke-PythonCommand -PythonCommand $pythonCmd -Args @("-m", "venv", $venvDir)
}

function Invoke-Pip {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Args
    )
    & $venvPython -m pip @Args
    if ($LASTEXITCODE -ne 0) {
        throw "pip failed: $($Args -join ' ')"
    }
}

function Install-Requirements {
    $requirements = Join-Path $comfyDir "requirements.txt"
    if (-not (Test-Path $requirements)) {
        throw "ComfyUI requirements.txt not found at $requirements"
    }

    Ensure-PipBase
    Ensure-TorchCuda
    Ensure-PythonDeps -RequirementsFile $requirements -Label "ComfyUI core"

    $customReqs = Get-ChildItem -Path (Join-Path $comfyDir "custom_nodes") -Recurse -Filter requirements.txt -File -ErrorAction SilentlyContinue
    foreach ($req in $customReqs) {
        try {
            Ensure-PythonDeps -RequirementsFile $req.FullName -Label "custom-node $($req.Directory.Name)"
        } catch {
            Write-Warning "Custom-node requirements failed for $($req.FullName). Continuing."
        }
    }

    Ensure-VideoExtras
    Ensure-OptionalFlashAttention
}

function Get-ComfyFlags {
    if (Test-Path Env:\GUAARDVARK_COMFYUI_FLAGS) {
        $rawFlags = $env:GUAARDVARK_COMFYUI_FLAGS
        if ([string]::IsNullOrWhiteSpace($rawFlags)) {
            return @()
        }
        return @($rawFlags -split '\s+' | Where-Object { $_ -and $_.Trim() })
    }
    return $defaultFlags
}

function Start-ComfyUi {
    $port = Get-ComfyPort
    $flags = Get-ComfyFlags
    $logDir = Join-Path $repoRoot "logs"
    $logFile = Join-Path $logDir "comfyui-windows.log"
    $errFile = Join-Path $logDir "comfyui-windows.err.log"
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null

    $existing = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq $port } | Select-Object -First 1
    if ($existing) {
        Write-Host "A process is already listening on port $port. Not starting another ComfyUI." -ForegroundColor Yellow
        return
    }

    $env:PYTORCH_CUDA_ALLOC_CONF = "expandable_segments:True"
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    $env:GUAARDVARK_ROOT = $repoRoot
    $env:GUAARDVARK_EXTERNAL_COMFYUI = "1"

    $argList = @(
        "main.py",
        "--listen",
        "--port",
        "$port"
    )
    $argList += $flags

    Write-Host "Launching native Windows ComfyUI on port $port" -ForegroundColor Green
    Start-Process -FilePath $venvPython `
        -WorkingDirectory $comfyDir `
        -ArgumentList $argList `
        -WindowStyle Hidden `
        -RedirectStandardOutput $logFile `
        -RedirectStandardError $errFile | Out-Null
}

if (-not (Test-Path $comfyDir)) {
    throw "Bundled ComfyUI checkout not found at $comfyDir"
}

Ensure-Venv
Install-Requirements
Start-ComfyUi
