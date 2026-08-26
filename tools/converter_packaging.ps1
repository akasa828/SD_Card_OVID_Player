function Assert-ConverterChildPath {
    param([string]$Root, [string]$Path)
    $parent = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    $child = [IO.Path]::GetFullPath($Path)
    if (-not $child.StartsWith($parent + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Package path must stay inside '$parent': $child"
    }
    return $child
}

function Assert-ConverterPathWithoutLinks {
    param([string]$Path)
    $current = [IO.Path]::GetFullPath($Path)
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force -ErrorAction Stop
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Package paths cannot contain symbolic links or junctions: $current"
            }
        }
        $current = [IO.Path]::GetDirectoryName($current)
    }
}

function Get-ConverterTreeFiles {
    param([string]$Path)
    Assert-ConverterPathWithoutLinks $Path
    $pending = [Collections.Generic.Stack[string]]::new()
    $pending.Push($Path)
    while ($pending.Count) {
        $item = Get-Item -LiteralPath $pending.Pop() -Force -ErrorAction Stop
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Package contents cannot contain symbolic links or junctions: $($item.FullName)"
        }
        if ($item.PSIsContainer) {
            foreach ($child in Get-ChildItem -LiteralPath $item.FullName -Force -ErrorAction Stop) {
                $pending.Push($child.FullName)
            }
        } else {
            $item.FullName
        }
    }
}

function Find-ConverterInstaller {
    param([switch]$SkipInstaller)
    if ($SkipInstaller) { return $null }
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($candidate in @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe",
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    )) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    throw "Inno Setup was not found. Install Inno Setup 6, or use -SkipInstaller for the portable EXE and ZIP only."
}

function Get-ConverterStagingParent {
    param([string]$OutputRoot)
    $output = [IO.Path]::GetFullPath($OutputRoot)
    $temporary = [IO.Path]::GetTempPath()
    if ([IO.Path]::GetPathRoot($output) -eq [IO.Path]::GetPathRoot($temporary)) {
        return $temporary
    }
    return $output
}

function New-ConverterBuild {
    param([string]$OutputRoot, [string]$ToolsRoot, [string]$StageParent = '')
    $output = [IO.Path]::GetFullPath($OutputRoot)
    $tools = [IO.Path]::GetFullPath($ToolsRoot)
    if (-not $StageParent) { $StageParent = $output }
    $stageParentPath = [IO.Path]::GetFullPath($StageParent)
    if ([IO.Path]::GetPathRoot($output) -ne [IO.Path]::GetPathRoot($stageParentPath)) {
        throw 'The staging directory must be on the same drive as the output directory.'
    }
    foreach ($reserved in @([IO.Path]::GetPathRoot($output), $tools, (Split-Path -Parent $tools))) {
        if ($output.TrimEnd('\', '/') -eq $reserved.TrimEnd('\', '/')) {
            throw "Use a dedicated output directory, not a drive, repository or tools root: $output"
        }
    }
    Assert-ConverterPathWithoutLinks $output
    Assert-ConverterPathWithoutLinks $tools
    Assert-ConverterPathWithoutLinks $stageParentPath
    $buildRoot = Join-Path $tools 'build'
    New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null
    Assert-ConverterPathWithoutLinks $buildRoot
    $lockPath = Join-Path $buildRoot '.converter-package.lock'
    Assert-ConverterPathWithoutLinks $lockPath
    try {
        $buildLock = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    } catch {
        throw "Cannot acquire the converter build lock. Another build may be running, or the build folder is not writable: $lockPath"
    }
    try {
        New-Item -ItemType Directory -Path $output -Force | Out-Null
        New-Item -ItemType Directory -Path $stageParentPath -Force | Out-Null
        $stage = Assert-ConverterChildPath $stageParentPath (Join-Path $stageParentPath ('.ovid-stage-' + [guid]::NewGuid().ToString('N')))
        New-Item -ItemType Directory -Path $stage -ErrorAction Stop | Out-Null
        return [pscustomobject]@{ OutputRoot = $output; StageRoot = $stage; StageParent = $stageParentPath; Lock = $buildLock }
    } catch {
        $buildLock.Dispose()
        throw
    }
}

function Get-ConverterArtifactNames {
    param(
        [ValidatePattern('^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$')][string]$Version,
        [switch]$WithInstaller
    )
    'portable/OVID Converter'
    'licenses'
    'THIRD_PARTY_NOTICES.txt'
    "OVID_Converter_Windows_x64_Portable_v$Version.zip"
    if ($WithInstaller) { "OVID_Converter_Windows_x64_Setup_v$Version.exe" }
}

function New-ConverterArchive {
    param([string]$PythonExecutable, [string]$AppRoot, [string]$ArchivePath)
    @(Get-ConverterTreeFiles $AppRoot) | Out-Null
    if (Test-Path -LiteralPath $ArchivePath) { throw "Archive already exists in the new build: $ArchivePath" }
    & $PythonExecutable -m zipfile -c $ArchivePath $AppRoot
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create the portable archive.' }
    & $PythonExecutable -m zipfile -t $ArchivePath
    if ($LASTEXITCODE -ne 0) { throw 'The portable archive failed its integrity check.' }
}

function Move-ConverterArtifact {
    param([string]$Source, [string]$Destination, [double]$RetrySeconds = 30)
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($Destination)) | Out-Null
    $isDirectory = (Get-Item -LiteralPath $Source -Force -ErrorAction Stop).PSIsContainer
    $waiting = [Diagnostics.Stopwatch]::StartNew()
    for ($attempt = 0; ; $attempt++) {
        try {
            if ($isDirectory) { [IO.Directory]::Move($Source, $Destination) }
            else { [IO.File]::Move($Source, $Destination) }
            return
        } catch {
            $code = $_.Exception.GetBaseException().HResult -band 0xFFFF
            if ($waiting.Elapsed.TotalSeconds -ge $RetrySeconds -or $code -notin @(5, 32, 33)) {
                $moveError = $_.Exception.Message
                $busyFiles = @()
                foreach ($file in @(Get-ConverterTreeFiles $Source)) {
                    try {
                        $probe = [IO.File]::Open($file, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None)
                        $probe.Dispose()
                    } catch { $busyFiles += $file }
                }
                $details = if ($busyFiles.Count) { " Files currently in use: $($busyFiles -join '; ')" } else { '' }
                throw "Cannot move '$Source' to '$Destination' (Windows error $code): $moveError.$details"
            }
            if ($attempt -eq 0) {
                Write-Host "Waiting for package files to be released (up to $RetrySeconds seconds): $Source"
            }
            $remaining = [Math]::Max(1, [Math]::Min(500, ($RetrySeconds - $waiting.Elapsed.TotalSeconds) * 1000))
            Start-Sleep -Milliseconds ([int]$remaining)
        }
    }
}

function Publish-ConverterArtifacts {
    param($Build, [string[]]$ArtifactNames)
    $stageParent = if ($Build.StageParent) { $Build.StageParent } else { $Build.OutputRoot }
    $stage = Assert-ConverterChildPath $stageParent $Build.StageRoot
    if ((Split-Path -Leaf $stage) -notmatch '^\.ovid-stage-[0-9a-f]{32}$') {
        throw "Refusing to publish from an unrecognized staging directory: $stage"
    }
    Assert-ConverterPathWithoutLinks $stage
    $backup = Join-Path $stage '.previous'
    if (Test-Path -LiteralPath $backup) {
        $previousFiles = @(Get-ConverterTreeFiles $backup)
        if ($previousFiles.Count) {
            throw "A previous publication needs recovery before retrying: $backup"
        }
    }
    $artifacts = @()
    foreach ($name in $ArtifactNames) {
        if ([IO.Path]::IsPathRooted($name) -or $name -match '(^|[\\/])\.\.?([\\/]|$)') {
            throw "Artifact names must be relative paths without dot segments: $name"
        }
        $source = Assert-ConverterChildPath $stage (Join-Path $stage $name)
        $destination = Assert-ConverterChildPath $Build.OutputRoot (Join-Path $Build.OutputRoot $name)
        $previous = Assert-ConverterChildPath $backup (Join-Path $backup $name)
        foreach ($known in $artifacts) {
            if ($destination -eq $known.Destination -or
                $destination.StartsWith($known.Destination + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or
                $known.Destination.StartsWith($destination + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Artifact paths must not overlap: $name"
            }
        }
        if (-not (Test-Path -LiteralPath $source)) { throw "Required package artifact is missing: $source" }
        @(Get-ConverterTreeFiles $source) | Out-Null
        Assert-ConverterPathWithoutLinks $destination
        if (Test-Path -LiteralPath $destination) {
            foreach ($file in @(Get-ConverterTreeFiles $destination)) {
                try {
                    $probe = [IO.File]::Open($file, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None)
                    $probe.Dispose()
                } catch {
                    throw "Cannot replace '$file'. Close OVID Converter, archive viewers or other programs using this file, then retry. Old packages are unchanged; the new build is in '$stage'."
                }
            }
        }
        $artifacts += [pscustomobject]@{ Source = $source; Destination = $destination; Previous = $previous }
    }
    if (-not $artifacts.Count) { throw 'No package artifacts were selected.' }
    $backedUp = [Collections.Generic.List[object]]::new()
    $published = [Collections.Generic.List[object]]::new()
    try {
        foreach ($artifact in $artifacts) {
            if (Test-Path -LiteralPath $artifact.Destination) {
                Move-ConverterArtifact $artifact.Destination $artifact.Previous
                $backedUp.Add($artifact)
            }
        }
        foreach ($artifact in $artifacts) {
            Move-ConverterArtifact $artifact.Source $artifact.Destination
            $published.Add($artifact)
        }
    } catch {
        $publishError = $_.Exception.Message
        $rollbackErrors = [Collections.Generic.List[string]]::new()
        for ($i = $published.Count - 1; $i -ge 0; $i--) {
            try { Move-ConverterArtifact $published[$i].Destination $published[$i].Source }
            catch { $rollbackErrors.Add($_.Exception.Message) }
        }
        for ($i = $backedUp.Count - 1; $i -ge 0; $i--) {
            try { Move-ConverterArtifact $backedUp[$i].Previous $backedUp[$i].Destination }
            catch { $rollbackErrors.Add($_.Exception.Message) }
        }
        if ($rollbackErrors.Count) {
            throw "Package publication failed: $publishError. Recovery is incomplete; do not delete '$stage'. Previous files are preserved in '$backup'. Recovery errors: $($rollbackErrors -join '; ')"
        }
        throw "Package publication failed: $publishError. Previous packages were restored. New build retained in '$stage'. Close programs using the output files before retrying."
    }
    try {
        # Only this build's verified staging tree is removed, never OutputRoot.
        $cleanupPath = Assert-ConverterChildPath $stageParent $stage
        @(Get-ConverterTreeFiles $cleanupPath) | Out-Null
        Remove-Item -LiteralPath $cleanupPath -Recurse -Force -ErrorAction Stop
    } catch {
        Write-Warning "Packages were published, but temporary build files remain in '$stage': $($_.Exception.Message)"
    }
}
