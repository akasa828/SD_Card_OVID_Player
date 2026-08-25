param(
    [string]$Version = "1.3.0-beta.2",
    [string]$WindowsVersion = "1.3.0.2",
    [string]$OutputRoot = "",
    [string]$PythonExecutable = "",
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$toolsRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $toolsRoot
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $toolsRoot "dist"
}
$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
$buildRoot = Join-Path $toolsRoot "build"
$iconPath = Join-Path $buildRoot "ovid_converter.ico"
$assetsPath = Join-Path $toolsRoot "assets"
$portableRoot = Join-Path $OutputRoot "portable"

if (-not $PythonExecutable) {
    $pythonCandidates = @(
        (Join-Path $repoRoot ".venv\Scripts\python.exe"),
        (Join-Path $repoRoot ".venv-test\Scripts\python.exe")
    )
    if ($env:VIRTUAL_ENV) {
        $pythonCandidates = @((Join-Path $env:VIRTUAL_ENV "Scripts\python.exe")) + $pythonCandidates
    }
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $pythonCandidates += $pythonCommand.Source
    }
    $PythonExecutable = $pythonCandidates | Where-Object {
        $_ -and (Test-Path -LiteralPath $_)
    } | Select-Object -First 1
}
if (-not $PythonExecutable) {
    throw "Python was not found. Activate the converter build environment or pass -PythonExecutable."
}

if (Test-Path -LiteralPath $OutputRoot) {
    Remove-Item -LiteralPath $OutputRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $portableRoot -Force | Out-Null

& $PythonExecutable (Join-Path $toolsRoot "generate_converter_assets.py")
if ($LASTEXITCODE -ne 0) { throw "Failed to generate converter icon." }

& $PythonExecutable -m flet.cli pack (Join-Path $toolsRoot "ovid_converter_gui.py") `
    --onedir `
    --yes `
    --name "OVID Converter" `
    --icon $iconPath `
    --distpath $portableRoot `
    --product-name "OVID Converter" `
    --file-description "Material 3 media to OVID v2 converter" `
    --product-version $Version `
    --file-version $WindowsVersion `
    --company-name "riochihao" `
    --copyright "Copyright (c) 2026 riochihao" `
    --add-data "${assetsPath}:assets" `
    --hidden-import imageio_ffmpeg `
    --pyinstaller-build-args=--exclude-module=flet_web
if ($LASTEXITCODE -ne 0) { throw "Flet packaging failed." }

$appRoot = Join-Path $portableRoot "OVID Converter"
if (-not (Test-Path -LiteralPath (Join-Path $appRoot "OVID Converter.exe"))) {
    throw "Packaged executable was not found."
}

& $PythonExecutable (Join-Path $toolsRoot "collect_converter_licenses.py") `
    --output-root $OutputRoot `
    --app-root $appRoot
if ($LASTEXITCODE -ne 0) { throw "Failed to collect third-party licenses." }
Copy-Item -LiteralPath (Join-Path $OutputRoot "THIRD_PARTY_NOTICES.txt") -Destination $appRoot
Copy-Item -LiteralPath (Join-Path $OutputRoot "licenses") -Destination $appRoot -Recurse

$ffmpeg = Get-ChildItem -LiteralPath $appRoot -Recurse -File | Where-Object { $_.Name -match '^ffmpeg.*\.exe$' }
if (-not $ffmpeg) {
    throw "The imageio-ffmpeg executable was not bundled."
}

$archive = Join-Path $OutputRoot "OVID_Converter_Windows_x64_Portable_v$Version.zip"
Compress-Archive -LiteralPath $appRoot -DestinationPath $archive -CompressionLevel Optimal

$isccPath = $null
if (-not $SkipInstaller) {
    $isccCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    $isccPath = if ($isccCommand) { $isccCommand.Source } else { $null }
    if (-not $isccPath) {
        $candidates = @(
            "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
            "C:\Program Files\Inno Setup 6\ISCC.exe",
            (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
        )
        foreach ($candidate in $candidates) {
            if (Test-Path -LiteralPath $candidate) {
                $isccPath = $candidate
                break
            }
        }
    }
}
if ($isccPath) {
    & $isccPath (Join-Path $toolsRoot "installer\OVID_Converter.iss") `
        "/DAppVersion=$Version" `
        "/DWindowsVersion=$WindowsVersion" `
        "/DSourceDir=$appRoot" `
        "/DOutputDir=$OutputRoot"
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup packaging failed." }
} elseif (-not $SkipInstaller) {
    throw "Inno Setup was not found; Setup.exe cannot be built."
} else {
    Write-Host "Installer skipped; portable EXE and ZIP were still created."
}

Write-Host "Portable package: $archive"
