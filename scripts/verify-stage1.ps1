<#
.SYNOPSIS
Prepare a local venv and run Stage 1 acceptance checks.
.EXAMPLE
.\scripts\verify-stage1.ps1 -StartPostgres
.EXAMPLE
.\scripts\verify-stage1.ps1 -UnitOnly -Wheelhouse C:\wheels
#>
[CmdletBinding()]
param(
    [string]$Python = 'python',
    [string]$Wheelhouse,
    [switch]$StartPostgres,
    [switch]$UnitOnly,
    [ValidateRange(1024, 65535)]
    [int]$PostgresPort = 55432
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Executable failed (exit code $LASTEXITCODE). Fix the error above and rerun this script."
    }
}

if ($UnitOnly -and $StartPostgres) {
    throw 'Choose either -UnitOnly or -StartPostgres.'
}
if (-not $UnitOnly -and -not $StartPostgres -and -not $env:FASTMIGRATE_TEST_DATABASE_URL) {
    throw 'Set FASTMIGRATE_TEST_DATABASE_URL for a dedicated test DB, or use -StartPostgres. Use -UnitOnly for partial verification.'
}
if ($Wheelhouse) {
    $Wheelhouse = (Resolve-Path -LiteralPath $Wheelhouse).Path
    if (-not (Test-Path -LiteralPath $Wheelhouse -PathType Container)) {
        throw 'Wheelhouse must be a directory containing dependency wheels.'
    }
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot '.venv/Scripts/python.exe'
$composeFile = Join-Path $projectRoot 'compose.test.yaml'
# A new project name ensures cleanup can only affect this run's test container.
$composeProject = 'fastmigrate-check-' + [guid]::NewGuid().ToString('N')
$composeArgs = @('compose', '--project-name', $composeProject, '--file', $composeFile)
$oldDatabaseUrl = $env:FASTMIGRATE_TEST_DATABASE_URL
$oldTestPort = $env:FASTMIGRATE_TEST_PORT
$containerAttempted = $false

Push-Location -LiteralPath $projectRoot
try {
    if ($StartPostgres) {
        Invoke-Checked 'docker' @('info', '--format', '{{.ServerVersion}}')
        Invoke-Checked 'docker' @('compose', 'version')
    }
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Invoke-Checked $Python @('-m', 'venv', '.venv')
    }
    Invoke-Checked $venvPython @('-c', "import sys; assert sys.version_info >= (3, 10), 'Python 3.10+ is required'")
    & $venvPython -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('pip') else 1)"
    if ($LASTEXITCODE -ne 0) {
        Invoke-Checked $venvPython @('-m', 'ensurepip', '--upgrade')
    }

    $extras = if ($UnitOnly) { '.[test]' } else { '.[postgres,test]' }
    $installArgs = @('-m', 'pip', 'install', '--disable-pip-version-check')
    if ($Wheelhouse) {
        $installArgs += @('--no-index', '--find-links', $Wheelhouse)
    }
    # Respect pip's existing proxy/index settings; do not modify global config.
    $installArgs += @('-e', $extras)
    Invoke-Checked $venvPython $installArgs

    if ($StartPostgres) {
        $env:FASTMIGRATE_TEST_PORT = [string]$PostgresPort
        $containerAttempted = $true
        Invoke-Checked 'docker' ($composeArgs + @('up', '--detach', '--wait', '--wait-timeout', '60'))
        $env:FASTMIGRATE_TEST_DATABASE_URL = "postgresql+psycopg://fastmigrate:fastmigrate_test@127.0.0.1:$PostgresPort/fastmigrate_test"
    }

    Write-Host 'Running the three original tests...'
    Invoke-Checked $venvPython @('-m', 'pytest', '-q', 'tests/test_runner.py', '--junitxml=.tmp/stage1-original.xml')
    $testArgs = @('-m', 'pytest', '-q', '-ra', '--strict-markers', '--cov=fastmigrate', '--cov-report=term-missing', '--cov-fail-under=80', '--junitxml=.tmp/stage1-results.xml')
    if ($UnitOnly) {
        $testArgs += @('-m', 'not postgres')
    }
    Invoke-Checked $venvPython $testArgs
    if ($UnitOnly) {
        Write-Host 'Unit/regression checks passed. PostgreSQL acceptance is still pending.'
    } else {
        Write-Host 'Stage 1 test suite passed, including PostgreSQL.'
    }
} finally {
    if ($containerAttempted) {
        & docker @composeArgs down --timeout 10
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Could not remove test project $composeProject. Clean up only this named project after checking Docker access."
        }
    }
    $env:FASTMIGRATE_TEST_DATABASE_URL = $oldDatabaseUrl
    $env:FASTMIGRATE_TEST_PORT = $oldTestPort
    Pop-Location
}
