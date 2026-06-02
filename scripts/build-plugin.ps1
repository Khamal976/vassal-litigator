# Build .plugin artifact for Claude Cowork.
#
# Places plugin contents at the ROOT of the archive (no wrapper folder).
# This is critical: Cowork validates `.claude-plugin/plugin.json` at the
# zip root.
#
# Usage:
#   pwsh scripts/build-plugin.ps1
#   pwsh scripts/build-plugin.ps1 -Version 0.6.1

[CmdletBinding()]
param(
    [string]$Version
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

# Parse `description` from a SKILL.md / command .md frontmatter and return
# the resolved string value (folded `>` lines joined with single space,
# single-line and quoted forms returned as-is). Reads as UTF-8 explicitly:
# Get-Content -Raw on Windows PowerShell 5.1 uses the system codepage,
# which double-counts every Cyrillic byte and silently corrupts the value.
# Returns $null if no frontmatter or no description field.
function Get-FrontmatterDescription {
    param([Parameter(Mandatory)][string]$Path)
    $text = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
    if ($text -notmatch '(?ms)\A---\r?\n(.*?)\r?\n---\s*(?:\r?\n|\z)') { return $null }
    $fm = $matches[1]
    # Folded block scalar: `description: >` (with optional chomp -/+) then indented body
    if ($fm -match '(?ms)^description:[ \t]*>[-+]?[ \t]*\r?\n((?:(?:[ \t]+[^\r\n]*|[ \t]*)(?:\r?\n|\z))+)') {
        $lines = $matches[1] -split '\r?\n' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
        return ($lines -join ' ')
    }
    # Literal block scalar: `description: |` — preserves line breaks
    if ($fm -match '(?ms)^description:[ \t]*\|[-+]?[ \t]*\r?\n((?:(?:[ \t]+[^\r\n]*|[ \t]*)(?:\r?\n|\z))+)') {
        $lines = $matches[1] -split '\r?\n' | ForEach-Object { $_.TrimEnd() }
        while ($lines.Count -gt 0 -and -not $lines[-1].Trim()) { $lines = $lines[0..($lines.Count - 2)] }
        return (($lines | ForEach-Object { $_.TrimStart() }) -join "`n")
    }
    # Plain or quoted single-line scalar
    if ($fm -match '(?m)^description:[ \t]*(.+?)[ \t]*$') {
        $v = $matches[1]
        if ($v -match '^"(.*)"$' -or $v -match "^'(.*)'$") { $v = $matches[1] }
        return $v
    }
    return $null
}

if (-not $Version) {
    $manifest = Get-Content (Join-Path $repoRoot '.claude-plugin/plugin.json') -Raw | ConvertFrom-Json
    $Version = $manifest.version
}

$distDir = Join-Path $repoRoot 'dist'
if (-not (Test-Path $distDir)) { New-Item -ItemType Directory -Path $distDir | Out-Null }

$stagingRoot = Join-Path $env:TEMP "vassal-litigator-build-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $stagingRoot -Force | Out-Null

# Whitelist: only these top-level entries ship in the .plugin artifact.
# Whitelist (not blacklist) avoids accidentally shipping internal docs,
# research dumps, or future top-level files that don't belong in a release.
$include = @(
    '.claude-plugin',
    '.mcp.json',
    'commands',
    'skills',
    'scripts',
    'shared',
    'README.md',
    'CHANGELOG.md',
    'LICENSE'
)

# Per-subtree directory excludes (e.g. python caches, virtualenvs, IDE
# metadata, internal reviews/ that lives under scripts or skills someday).
$excludeDirs = @('__pycache__', '.venv', 'venv', '.vscode', '.idea')
$excludeFiles = @('.DS_Store', '*.pyc', '*.pyo')

foreach ($entry in $include) {
    $src = Join-Path $repoRoot $entry
    if (-not (Test-Path $src)) {
        Write-Warning "skip missing: $entry"
        continue
    }
    $dst = Join-Path $stagingRoot $entry

    if ((Get-Item $src).PSIsContainer) {
        $robocopyArgs = @($src, $dst, '/S', '/XD') + $excludeDirs + @('/XF') + $excludeFiles + @('/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:1', '/W:1')
        & robocopy @robocopyArgs | Out-Null
        if ($LASTEXITCODE -ge 8) {
            Remove-Item $stagingRoot -Recurse -Force -ErrorAction SilentlyContinue
            throw "robocopy failed with code $LASTEXITCODE for $entry"
        }
        $global:LASTEXITCODE = 0
    } else {
        Copy-Item -Path $src -Destination $dst -Force
    }
}

# Self-check: manifest must end up at staging root.
$manifestStaged = Join-Path $stagingRoot '.claude-plugin/plugin.json'
if (-not (Test-Path $manifestStaged)) {
    Remove-Item $stagingRoot -Recurse -Force -ErrorAction SilentlyContinue
    throw 'plugin.json not staged at archive root — build aborted'
}

# Pre-flight: frontmatter description length.
# SKILL.md > 1024 chars is rejected by the Anthropic Cowork validator with a
# generic «Plugin validation failed» error (no field name, no length).
# See https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices
# and https://github.com/anthropics/claude-code/issues/56376 — local guard is
# the only way to get an actionable failure before upload.
# commands/*.md has no documented hard limit; ~250 chars is the display
# threshold per claude-code#44780, so we warn but don't abort.
$skillsStaged = Join-Path $stagingRoot 'skills'
$violations = @()
$warnings = @()
if (Test-Path $skillsStaged) {
    Get-ChildItem -Path $skillsStaged -Filter SKILL.md -Recurse -File | ForEach-Object {
        $rel = $_.FullName.Substring($stagingRoot.Length).TrimStart('\','/') -replace '\\','/'
        $desc = Get-FrontmatterDescription -Path $_.FullName
        if ($null -eq $desc) {
            $violations += "SKILL.md $rel -- no description field in frontmatter"
            return
        }
        $len = [System.Globalization.StringInfo]::new($desc).LengthInTextElements
        if ($len -gt 1024) {
            $violations += "SKILL.md $rel description = $len chars, max 1024 (Anthropic Cowork validator hard limit)"
        }
    }
}
$commandsStaged = Join-Path $stagingRoot 'commands'
if (Test-Path $commandsStaged) {
    Get-ChildItem -Path $commandsStaged -Filter *.md -File | ForEach-Object {
        $rel = $_.FullName.Substring($stagingRoot.Length).TrimStart('\','/') -replace '\\','/'
        $desc = Get-FrontmatterDescription -Path $_.FullName
        if ($null -eq $desc) { return }  # description is optional for commands
        $len = [System.Globalization.StringInfo]::new($desc).LengthInTextElements
        if ($len -gt 250) {
            $warnings += "command $rel description = $len chars (>250, may truncate in UI; no validator limit per claude-code#44780)"
        }
    }
}
foreach ($w in $warnings) { Write-Warning $w }
if ($violations.Count -gt 0) {
    Remove-Item $stagingRoot -Recurse -Force -ErrorAction SilentlyContinue
    $msg = "Frontmatter description-length pre-flight failed ($($violations.Count) violation(s)):`n  - " + ($violations -join "`n  - ")
    throw $msg
}

$outName = "vassal-litigator-$Version.plugin"
$outPath = Join-Path $distDir $outName
if (Test-Path $outPath) { Remove-Item $outPath -Force }

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
# Pack CONTENTS of $stagingRoot into the archive root with forward-slash
# paths. ZipFile.CreateFromDirectory on .NET Framework (Windows PowerShell
# 5.1) writes backslashes, which ZIP spec forbids and which cross-platform
# validators (e.g. Cowork) reject.
$stream = [System.IO.File]::Open($outPath, [System.IO.FileMode]::Create)
try {
    $zip = New-Object System.IO.Compression.ZipArchive(
        $stream,
        [System.IO.Compression.ZipArchiveMode]::Create
    )
    try {
        $stagingRootFull = (Resolve-Path $stagingRoot).Path
        Get-ChildItem -LiteralPath $stagingRoot -Recurse -File | ForEach-Object {
            $rel = $_.FullName.Substring($stagingRootFull.Length).TrimStart('\','/')
            $entryName = $rel -replace '\\','/'
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $zip,
                $_.FullName,
                $entryName,
                [System.IO.Compression.CompressionLevel]::Optimal
            ) | Out-Null
        }
    } finally {
        $zip.Dispose()
    }
} finally {
    $stream.Dispose()
}

Remove-Item $stagingRoot -Recurse -Force

$size = [math]::Round((Get-Item $outPath).Length / 1KB, 1)
Write-Host "Built $outName ($size KB) at $outPath"
