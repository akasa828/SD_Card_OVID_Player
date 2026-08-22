param(
    [string]$Version = "1.3.0-beta.2",
    [string]$WindowsVersion = "1.3.0.2",
    [string]$OutputRoot = "",
    [string]$PythonExecutable = "",
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$toolsRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $toolsRoot
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $toolsRoot "dist"
}
$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
$buildRoot = Join-Path $toolsRoot "build"
$flutterOutput = Join-Path $buildRoot "flutter-windows"
$portableRoot = Join-Path $OutputRoot "portable"
$appRoot = Join-Path $portableRoot "OVID Converter"

if (-not $PythonExecutable) {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $PythonExecutable = $pythonCommand.Source
    }
}
if (-not $PythonExecutable -or -not (Test-Path -LiteralPath $PythonExecutable)) {
    throw "Python was not found. Pass -PythonExecutable or activate the converter build environment."
}

if (Test-Path -LiteralPath $OutputRoot) {
    Remove-Item -LiteralPath $OutputRoot -Recurse -Force
}
if (Test-Path -LiteralPath $flutterOutput) {
    Remove-Item -LiteralPath $flutterOutput -Recurse -Force
}
New-Item -ItemType Directory -Path $appRoot -Force | Out-Null

$versionParts = $WindowsVersion.Split('.')
if ($versionParts.Count -ne 4) {
    throw "WindowsVersion must contain four numeric components."
}
$buildVersion = "$($versionParts[0]).$($versionParts[1]).$($versionParts[2])"
$buildNumber = $versionParts[3]

& $PythonExecutable (Join-Path $toolsRoot "generate_converter_assets.py")
if ($LASTEXITCODE -ne 0) { throw "Failed to generate converter assets." }

Push-Location $repoRoot
try {
    & $PythonExecutable -m flet.cli build windows `
        --output $flutterOutput `
        --project "ovid_converter" `
        --artifact "OVID Converter" `
        --product "OVID Converter" `
        --description "Material 3 media to OVID v2 converter" `
        --org "io.github.akasa828" `
        --company "riochihao" `
        --copyright "Copyright (c) 2026 riochihao" `
        --build-version $buildVersion `
        --build-number $buildNumber `
        --module-name "ovid_converter_gui" `
        --yes
    if ($LASTEXITCODE -ne 0) { throw "Flet Flutter build failed." }
} finally {
    Pop-Location
}

$executable = Get-ChildItem -LiteralPath $flutterOutput -Recurse -File -Filter "*.exe" |
    Where-Object { $_.Name -match "OVID|ovid_converter" } |
    Select-Object -First 1
if (-not $executable) {
    throw "The Flutter build completed but the OVID Converter executable was not found."
}
Copy-Item -Path (Join-Path $executable.Directory.FullName "*") -Destination $appRoot -Recurse -Force

$copiedExecutable = Join-Path $appRoot $executable.Name
$releaseExecutable = Join-Path $appRoot "OVID Converter.exe"
if ($copiedExecutable -ne $releaseExecutable) {
    Move-Item -LiteralPath $copiedExecutable -Destination $releaseExecutable -Force
}

& $PythonExecutable (Join-Path $toolsRoot "collect_converter_licenses.py") `
    --output-root $OutputRoot `
    --app-root $appRoot
if ($LASTEXITCODE -ne 0) { throw "Failed to collect third-party licenses." }
Copy-Item -LiteralPath (Join-Path $OutputRoot "THIRD_PARTY_NOTICES.txt") -Destination $appRoot
Copy-Item -LiteralPath (Join-Path $OutputRoot "licenses") -Destination $appRoot -Recurse

$archive = Join-Path $OutputRoot "OVID_Converter_Windows_x64_Portable_v$Version.zip"
Compress-Archive -LiteralPath $appRoot -DestinationPath $archive -CompressionLevel Optimal

$isccPath = $null
if (-not $SkipInstaller) {
    $isccCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    $isccPath = if ($isccCommand) { $isccCommand.Source } else { $null }
    if (-not $isccPath) {
        foreach ($candidate in @(
            "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
            "C:\Program Files\Inno Setup 6\ISCC.exe",
            (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
        )) {
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
}

Write-Host "Full portable package: $archive"
