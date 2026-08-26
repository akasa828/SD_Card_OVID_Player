param(
    [ValidatePattern('^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$')]
    [string]$Version = "1.3.2-beta.1",
    [ValidatePattern('^\d+\.\d+\.\d+\.\d+$')]
    [string]$WindowsVersion = "1.3.2.1",
    [string]$OutputRoot = "",
    [string]$PythonExecutable = "",
    [switch]$SkipInstaller
)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$toolsRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $toolsRoot
. (Join-Path $toolsRoot 'converter_packaging.ps1')
if (-not $OutputRoot) { $OutputRoot = Join-Path $toolsRoot 'dist' }
$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
if (-not $PythonExecutable) {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCommand) { $PythonExecutable = $pythonCommand.Source }
}
if (-not $PythonExecutable -or -not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
    throw 'Python was not found. Pass -PythonExecutable or activate the converter build environment.'
}
$isccPath = Find-ConverterInstaller -SkipInstaller:$SkipInstaller
$packageBuild = New-ConverterBuild -OutputRoot $OutputRoot -ToolsRoot $toolsRoot -StageParent (Get-ConverterStagingParent $OutputRoot)
$stageRoot = $packageBuild.StageRoot
$flutterOutput = Join-Path $stageRoot 'flutter-windows'
$appRoot = Join-Path $stageRoot 'portable/OVID Converter'
$versionParts = $WindowsVersion.Split('.')
$buildVersion = "$($versionParts[0]).$($versionParts[1]).$($versionParts[2])"
$buildNumber = $versionParts[3]
$archiveName = "OVID_Converter_Windows_x64_Portable_v$Version.zip"
try {
    New-Item -ItemType Directory -Path $appRoot -Force | Out-Null
    & $PythonExecutable (Join-Path $toolsRoot 'generate_converter_assets.py')
    if ($LASTEXITCODE -ne 0) { throw 'Failed to generate converter assets.' }
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
        if ($LASTEXITCODE -ne 0) { throw 'Flet Flutter build failed.' }
    } finally {
        Pop-Location
    }
    $executable = Get-ChildItem -LiteralPath $flutterOutput -Recurse -File -Filter '*.exe' |
        Where-Object { $_.Name -match 'OVID|ovid_converter' } | Select-Object -First 1
    if (-not $executable) {
        throw 'The Flutter build completed but the OVID Converter executable was not found.'
    }
    foreach ($item in Get-ChildItem -LiteralPath $executable.Directory.FullName -Force) {
        Copy-Item -LiteralPath $item.FullName -Destination $appRoot -Recurse
    }
    $copiedExecutable = Join-Path $appRoot $executable.Name
    $releaseExecutable = Join-Path $appRoot 'OVID Converter.exe'
    if ($copiedExecutable -ne $releaseExecutable) {
        Move-ConverterArtifact $copiedExecutable $releaseExecutable
    }
    & $PythonExecutable (Join-Path $toolsRoot 'collect_converter_licenses.py') `
        --output-root $stageRoot --app-root $appRoot
    if ($LASTEXITCODE -ne 0) { throw 'Failed to collect third-party licenses.' }
    Copy-Item -LiteralPath (Join-Path $stageRoot 'THIRD_PARTY_NOTICES.txt') -Destination $appRoot
    Copy-Item -LiteralPath (Join-Path $stageRoot 'licenses') -Destination $appRoot -Recurse
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
Write-Host "Full portable package: $(Join-Path $OutputRoot $archiveName)"
