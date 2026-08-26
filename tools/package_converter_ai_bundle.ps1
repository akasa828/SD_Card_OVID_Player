param(
    [string]$Version = "1.3.1",
    [string]$RuntimeRoot = "",
    [string]$OutputRoot = ""
)

$ErrorActionPreference = "Stop"
$toolsRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $toolsRoot
if (-not $RuntimeRoot) {
    $RuntimeRoot = Join-Path $toolsRoot "dist\portable\OVID Converter"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $toolsRoot "dist"
}
$RuntimeRoot = [System.IO.Path]::GetFullPath($RuntimeRoot)
$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)

$executable = Join-Path $RuntimeRoot "OVID Converter.exe"
if (-not (Test-Path -LiteralPath $executable)) {
    throw "Portable runtime was not found: $executable"
}

New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
$stagingRoot = Join-Path ([System.IO.Path]::GetTempPath()) (
    "ovid-converter-ai-bundle-" + [guid]::NewGuid().ToString("N")
)
$bundleRoot = Join-Path $stagingRoot "OVID_Converter_AI_Bundle_v$Version"
$sourceRoot = Join-Path $bundleRoot "source"
$runtimeTarget = Join-Path $bundleRoot "runtime\OVID Converter"
$archive = Join-Path $OutputRoot "OVID_Converter_AI_Source_Bundle_v$Version.zip"

try {
    New-Item -ItemType Directory -Path $sourceRoot -Force | Out-Null
    New-Item -ItemType Directory -Path (Split-Path -Parent $runtimeTarget) -Force | Out-Null
    Copy-Item -LiteralPath $RuntimeRoot -Destination $runtimeTarget -Recurse

    $rootFiles = @(
        "Build_OVID_Converter.bat",
        "OVID Converter.spec",
        "pyproject.toml",
        "README.md",
        "README_EN.md",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "LICENSE"
    )
    foreach ($name in $rootFiles) {
        $source = Join-Path $repoRoot $name
        if (Test-Path -LiteralPath $source) {
            Copy-Item -LiteralPath $source -Destination $sourceRoot
        }
    }

    $sourceTools = Join-Path $repoRoot "tools"
    $targetTools = Join-Path $sourceRoot "tools"
    & robocopy $sourceTools $targetTools /E /XD build dist __pycache__ .pytest_cache /XF *.pyc | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "Failed to copy converter sources (robocopy exit code $LASTEXITCODE)."
    }

    $workflow = Join-Path $repoRoot ".github\workflows\release-assets.yml"
    if (Test-Path -LiteralPath $workflow) {
        $workflowTarget = Join-Path $sourceRoot ".github\workflows"
        New-Item -ItemType Directory -Path $workflowTarget -Force | Out-Null
        Copy-Item -LiteralPath $workflow -Destination $workflowTarget
    }

    $revision = (& git -C $repoRoot rev-parse HEAD 2>$null)
    if (-not $revision) {
        $revision = "unknown"
    }
    $guide = @'
# OVID Converter AI analysis bundle

Version: v{VERSION}
Git revision: {REVISION}

This archive contains both the runnable Windows x64 portable application and
the complete converter source needed to inspect, test, modify, and rebuild it.

## Directory layout

- `runtime/OVID Converter/OVID Converter.exe`: ready-to-run application.
- `source/tools/ovid_converter_gui.py`: Flet Material 3 desktop UI.
- `source/tools/media2ovid.py`: media decoding and conversion pipeline.
- `source/tools/converter_services.py`: tasks, presets, validation, and logs.
- `source/tools/ovid_codec.py`: OVID v1/v2 reader and writer primitives.
- `source/tools/ovid_player.py`: desktop OVID playback simulator.
- `source/tools/extensions/flet_drop_zone/`: native desktop drag-and-drop extension.
- `source/tools/tests/`: Python regression tests.
- `source/Build_OVID_Converter.bat`: local Windows build entry point.
- `source/tools/package_converter.ps1`: portable/installer packaging logic.

## Run from source

Use Python 3.10-3.15 on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r tools\requirements-converter.txt
.\.venv\Scripts\python.exe tools\ovid_converter_gui.py
```

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tools\tests -p "test_*.py"
```

The `runtime` directory is generated output. Make code changes under `source`,
then rebuild instead of editing packaged `_internal` files.
'@
    $guide = $guide.Replace("{VERSION}", $Version).Replace("{REVISION}", $revision)
    Set-Content -LiteralPath (Join-Path $bundleRoot "AI_ANALYSIS_GUIDE.md") -Value $guide -Encoding utf8

    if (Test-Path -LiteralPath $archive) {
        Remove-Item -LiteralPath $archive -Force
    }
    Compress-Archive -Path (Join-Path $bundleRoot "*") -DestinationPath $archive -CompressionLevel Optimal
    Write-Host "AI analysis bundle: $archive"
}
finally {
    if (Test-Path -LiteralPath $stagingRoot) {
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force
    }
}
