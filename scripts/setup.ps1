# setup.ps1 -- Install Python dependencies for vassal-litigator on Windows.
#
# Why a separate script: setup.sh is bash and does not run in PowerShell, so on a
# native Windows machine the plugin had no installer at all. Found 2026-07-30, when
# openpyxl turned out to be missing on the Suzerain's machine while every check in
# the agent's sandbox passed -- the sandbox has its own site-packages.
#
# NOTE (project convention, see OPEN-ITEMS): .ps1 files here are kept in English
# ASCII. Windows PowerShell 5.1 reads .ps1 without BOM in the system codepage, and
# Cyrillic in comments breaks the parser.
#
# Usage:   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
# Or just: python -m pip install PyYAML pymupdf python-docx openpyxl

$ErrorActionPreference = "Continue"
$deps = @("PyYAML", "pymupdf", "python-docx", "openpyxl")

Write-Output "=== vassal-litigator: Python dependencies (Windows) ==="

# Resolve an interpreter that actually works. On Windows `python3` is often a
# WindowsApps stub pointing at a different build without the dependencies, so
# `python` is tried first here (mirror of conventions.md, feature-detection p.0).
$py = $null
foreach ($cand in @("python", "py -3", "python3")) {
    $parts = $cand -split " "
    $exe = $parts[0]
    $rest = if ($parts.Count -gt 1) { $parts[1..($parts.Count - 1)] } else { @() }
    $cmd = Get-Command $exe -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    $probe = & $exe @rest -c "import sys; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $probe) {
        $py = @{ exe = $exe; rest = $rest; path = $probe }
        break
    }
}

if (-not $py) {
    Write-Output "FAILED: no working Python found (tried python, py -3, python3)."
    Write-Output "Install Python 3.10+ and re-run."
    exit 1
}

Write-Output ("Interpreter: " + $py.path)

# pip may be absent as a standalone command; `-m pip` is the reliable form.
$pipCheck = & $py.exe @($py.rest + @("-m", "pip", "--version")) 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Output "FAILED: pip is unavailable for this interpreter."
    Write-Output ("Try: " + '"' + $py.path + '"' + " -m ensurepip --upgrade")
    exit 1
}

$log = Join-Path $env:TEMP "vassal-setup-pip.log"
Write-Output ("Installing: " + ($deps -join ", "))
& $py.exe @($py.rest + @("-m", "pip", "install", "--upgrade") + $deps) *> $log
$installExit = $LASTEXITCODE

# Verify by IMPORT, not by pip exit code: a package can be "installed" while its
# own dependency is missing, and pip still reports success.
$modules = @{ "PyYAML" = "yaml"; "pymupdf" = "fitz"; "python-docx" = "docx"; "openpyxl" = "openpyxl" }
$failed = @()
foreach ($dep in $deps) {
    $mod = $modules[$dep]
    & $py.exe @($py.rest + @("-c", "import $mod")) 2>$null
    if ($LASTEXITCODE -eq 0) {
        $ver = & $py.exe @($py.rest + @("-c", "import $mod,sys; print(getattr($mod,'__version__','?'))")) 2>$null
        Write-Output ("  OK   " + $dep + "  (" + $ver + ")")
    } else {
        Write-Output ("  FAIL " + $dep + "  (import $mod)")
        $failed += $dep
    }
}

if ($failed.Count -gt 0) {
    Write-Output ""
    Write-Output ("Not importable: " + ($failed -join ", "))
    Write-Output ("pip log: " + $log + "  (exit code " + $installExit + ")")
    Write-Output "If pip reported success but import fails, the package directory may be"
    Write-Output "excluded from sys.path -- check:"
    Write-Output ("  " + '"' + $py.path + '"' + " -c ""import site,sys; print(site.ENABLE_USER_SITE, sys.flags.no_user_site)""")
    exit 1
}

Write-Output ""
Write-Output "All dependencies importable. Verify the table analyzer:"
Write-Output "  python scripts\analyze_table.py --selftest"
exit 0
