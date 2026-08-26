param([string]$Root, [string]$Helpers, [string]$Scenario, [string]$PythonExecutable)
$ErrorActionPreference = 'Stop'
. $Helpers
$build = $null
$heldFile = $null
$sourceHolder = $null
try {
    $stageParent = if ($Scenario -eq 'separate-stage') { Join-Path $Root 'staging' } else { Join-Path $Root 'output' }
    $build = New-ConverterBuild -OutputRoot (Join-Path $Root 'output') -ToolsRoot (Join-Path $Root 'checkout/tools') -StageParent $stageParent
    Write-Output "STAGE=$($build.StageRoot)"
    if ($Scenario -eq 'concurrent') {
        $second = New-ConverterBuild -OutputRoot (Join-Path $Root 'other-output') -ToolsRoot (Join-Path $Root 'checkout/tools')
        $second.Lock.Dispose()
        throw 'Second build unexpectedly acquired the lock'
    }
    foreach ($item in Get-ChildItem -LiteralPath (Join-Path $Root 'payload') -Force) {
        Copy-Item -LiteralPath $item.FullName -Destination $build.StageRoot -Recurse
    }
    $names = @(Get-ConverterArtifactNames -Version '1.3.0-beta.2' -WithInstaller:($Scenario -eq 'installer'))
    if ($Scenario -eq 'archive') {
        New-ConverterArchive -PythonExecutable $PythonExecutable -AppRoot (Join-Path $build.StageRoot 'portable/OVID Converter') -ArchivePath (Join-Path $build.StageRoot 'OVID_Converter_Windows_x64_Portable_v1.3.0-beta.2.zip')
    }
    if ($Scenario -eq 'persistent-source-lock') {
        $sourceFile = Join-Path $build.StageRoot 'portable/OVID Converter/OVID Converter.exe'
        $heldFile = [IO.File]::Open($sourceFile, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None)
        Move-ConverterArtifact $sourceFile (Join-Path $build.StageRoot 'new.exe') -RetrySeconds 0.1
        throw 'Locked source was unexpectedly moved'
    }
    if ($Scenario -eq 'empty-backup-retry') {
        New-Item -ItemType Directory -Path (Join-Path $build.StageRoot '.previous/portable') -Force | Out-Null
    }
    if ($Scenario -eq 'unfinished-recovery') {
        $backupRoot = Join-Path $build.StageRoot '.previous'
        New-Item -ItemType Directory -Path $backupRoot | Out-Null
        Copy-Item -LiteralPath (Join-Path $build.OutputRoot 'THIRD_PARTY_NOTICES.txt') -Destination $backupRoot
    }
    if ($Scenario -eq 'escape') { $names += '../outside.txt' }
    if ($Scenario -eq 'overlap') { $names += 'portable' }
    if ($Scenario -in @('locked-zip', 'locked-exe', 'cleanup-failure')) {
        if ($Scenario -eq 'locked-zip') {
            $locked = Join-Path $build.OutputRoot 'OVID_Converter_Windows_x64_Portable_v1.3.0-beta.2.zip'
        } elseif ($Scenario -eq 'locked-exe') {
            $locked = Join-Path $build.OutputRoot 'portable/OVID Converter/OVID Converter.exe'
        } else {
            $locked = Join-Path $build.StageRoot 'unavailable.tmp'
        }
        $heldFile = [IO.File]::Open($locked, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    }
    if ($Scenario -in @('late-failure', 'rollback-failure')) {
        $script:realMove = (Get-Command Move-ConverterArtifact).ScriptBlock
        $script:moveCount = 0
        function Move-ConverterArtifact {
            param([string]$Source, [string]$Destination)
            $script:moveCount++
            if ($script:moveCount -eq 6 -or ($Scenario -eq 'rollback-failure' -and $script:moveCount -eq 7)) {
                throw 'Injected move failure'
            }
            & $script:realMove -Source $Source -Destination $Destination
        }
    }
    if ($Scenario -in @('destination-junction', 'source-junction')) {
        $linkRoot = if ($Scenario -eq 'destination-junction') { $build.OutputRoot } else { $build.StageRoot }
        Push-Location -LiteralPath (Join-Path $linkRoot 'portable/OVID Converter')
        try {
            New-Item -ItemType Junction -Path 'linked' -Target ([WildcardPattern]::Escape((Join-Path $Root 'external'))) | Out-Null
        } finally {
            Pop-Location
        }
    }
    if ($Scenario -eq 'transient-source-lock') {
        $sourceHolder = [PowerShell]::Create()
        $ready = [Threading.ManualResetEvent]::new($false)
        $holdScript = {
            param($Path, $Ready)
            $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None)
            try {
                $Ready.Set() | Out-Null
                Start-Sleep -Milliseconds 1000
            } finally {
                $stream.Dispose()
            }
        }
        $sourceHolder.AddScript($holdScript).AddArgument((Join-Path $build.StageRoot 'portable/OVID Converter/OVID Converter.exe')).AddArgument($ready) | Out-Null
        $sourceWork = $sourceHolder.BeginInvoke()
        if (-not $ready.WaitOne(5000)) { throw 'Test file lock was not acquired' }
    }
    Publish-ConverterArtifacts -Build $build -ArtifactNames $names
    Write-Output 'PUBLISHED'
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
} finally {
    if ($heldFile) { $heldFile.Dispose() }
    if ($sourceHolder) {
        $sourceHolder.EndInvoke($sourceWork) | Out-Null
        $sourceHolder.Dispose()
        $ready.Dispose()
    }
    if ($build) { $build.Lock.Dispose() }
}
