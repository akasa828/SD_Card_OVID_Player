param(
    [ValidatePattern('^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$')]
    [string]$Version = "1.3.0-beta.2",
    [ValidatePattern('^\d+\.\d+\.\d+\.\d+$')]
    [string]$WindowsVersion = "1.3.0.2",
    [string]$OutputRoot = "",
    [string]$PythonExecutable = "",
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$toolsRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $toolsRoot
. (Join-Path $toolsRoot 'converter_packaging.ps1')
if (-not $OutputRoot) { $OutputRoot = Join-Path $toolsRoot 'dist' }
$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
$iconPath = Join-Path $toolsRoot 'build/ovid_converter.ico'
$assetsPath = Join-Path $toolsRoot 'assets'

if (-not $PythonExecutable) {
    $pythonCandidates = @(
        (Join-Path $repoRoot '.venv-converter-build/Scripts/python.exe'),
        (Join-Path $repoRoot '.venv/Scripts/python.exe'),
        (Join-Path $repoRoot '.venv-test/Scripts/python.exe')
    )
    if ($env:VIRTUAL_ENV) {
        $pythonCandidates = @((Join-Path $env:VIRTUAL_ENV 'Scripts/python.exe')) + $pythonCandidates
    }
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCommand) { $pythonCandidates += $pythonCommand.Source }
    $PythonExecutable = $pythonCandidates | Where-Object {
        $_ -and (Test-Path -LiteralPath $_ -PathType Leaf)
    } | Select-Object -First 1
}
if (-not $PythonExecutable -or -not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
    throw 'Python was not found. Activate the converter build environment or pass -PythonExecutable.'
}
$isccPath = Find-ConverterInstaller -SkipInstaller:$SkipInstaller
$packageBuild = New-ConverterBuild -OutputRoot $OutputRoot -ToolsRoot $toolsRoot -StageParent (Get-ConverterStagingParent $OutputRoot)
$stageRoot = $packageBuild.StageRoot
$portableRoot = Join-Path $stageRoot 'portable'
$appRoot = Join-Path $portableRoot 'OVID Converter'
$archiveName = "OVID_Converter_Windows_x64_Portable_v$Version.zip"
try {
    New-Item -ItemType Directory -Path $portableRoot | Out-Null
    & $PythonExecutable (Join-Path $toolsRoot 'generate_converter_assets.py')
    if ($LASTEXITCODE -ne 0) { throw 'Failed to generate converter icon.' }
    & $PythonExecutable -m flet.cli pack (Join-Path $toolsRoot 'ovid_converter_gui.py') `
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
    if ($LASTEXITCODE -ne 0) { throw 'Flet packaging failed.' }
    if (-not (Test-Path -LiteralPath (Join-Path $appRoot 'OVID Converter.exe') -PathType Leaf)) {
        throw 'Packaged executable was not found.'
    }
    & $PythonExecutable (Join-Path $toolsRoot 'collect_converter_licenses.py') `
        --output-root $stageRoot --app-root $appRoot
    if ($LASTEXITCODE -ne 0) { throw 'Failed to collect third-party licenses.' }
    Copy-Item -LiteralPath (Join-Path $stageRoot 'THIRD_PARTY_NOTICES.txt') -Destination $appRoot
    Copy-Item -LiteralPath (Join-Path $stageRoot 'licenses') -Destination $appRoot -Recurse
    $ffmpeg = Get-ChildItem -LiteralPath $appRoot -Recurse -File |
        Where-Object { $_.Name -match '^ffmpeg.*\.exe$' }
    if (-not $ffmpeg) { throw 'The imageio-ffmpeg executable was not bundled.' }
    New-ConverterArchive -PythonExecutable $PythonExecutable -AppRoot $appRoot -ArchivePath (Join-Path $stageRoot $archiveName)
    if ($isccPath) {
        & $isccPath (Join-Path $toolsRoot 'installer/OVID_Converter.iss') `
            "/DAppVersion=$Version" "/DWindowsVersion=$WindowsVersion" `
            "/DSourceDir=$appRoot" "/DOutputDir=$stageRoot"
        if ($LASTEXITCODE -ne 0) { throw 'Inno Setup packaging failed.' }
    }
    $artifacts = @(Get-ConverterArtifactNames -Version $Version -WithInstaller:([bool]$isccPath))
    Publish-ConverterArtifacts -Build $packageBuild -ArtifactNames $artifacts
} catch {
    Write-Warning "The build was not published. Available new files and recovery copies remain in '$stageRoot'."
    throw
} finally {
    $packageBuild.Lock.Dispose()
}
if ($SkipInstaller) { Write-Host 'Installer skipped; portable EXE and ZIP were still created.' }
Write-Host "Portable package: $(Join-Path $OutputRoot $archiveName)"
