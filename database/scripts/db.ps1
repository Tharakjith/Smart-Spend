<#
.SYNOPSIS
  SmartSpend database helper: regenerate the schema script, back up, or restore.

.EXAMPLE
  .\database\scripts\db.ps1 schema                       # rebuild database\01_schema.sql from the migrations
  .\database\scripts\db.ps1 backup                       # pg_dump to database\backups\smartspend-<time>.dump
  .\database\scripts\db.ps1 restore database\backups\smartspend-20261022-1530.dump

.NOTES
  The connection comes from DATABASE_URL (the same variable the API uses), e.g.
  postgresql+psycopg://smartspend:secret@localhost:5432/smartspend
  PostgreSQL client tools (pg_dump, pg_restore) are taken from PATH, or from the embedded
  PostgreSQL that scripts/dev.py uses when they aren't installed.
#>
param(
  [Parameter(Mandatory = $true, Position = 0)][ValidateSet("schema", "backup", "restore")][string]$Command,
  [Parameter(Position = 1)][string]$File
)
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

function Get-Tool([string]$Name) {
  $cmd = Get-Command $Name -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $embedded = Join-Path $Root ".venv\Lib\site-packages\pgserver\pginstall\bin\$Name.exe"
  if (Test-Path $embedded) { return $embedded }
  throw "$Name not found. Install the PostgreSQL client tools or add them to PATH."
}

function Get-Url {
  if (-not $env:DATABASE_URL) { throw "Set DATABASE_URL first, e.g. postgresql+psycopg://smartspend:secret@localhost:5432/smartspend" }
  # libpq tools don't understand SQLAlchemy's '+driver' suffix.
  return ($env:DATABASE_URL -replace '^postgresql\+[a-z0-9]+://', 'postgresql://')
}

switch ($Command) {
  "schema" {
    $out = Join-Path $Root "database\01_schema.sql"
    Push-Location (Join-Path $Root "backend")
    try {
      # Offline mode writes SQL without connecting; the URL only selects the PostgreSQL dialect.
      $saved = $env:DATABASE_URL
      $env:DATABASE_URL = "postgresql+psycopg://smartspend@localhost/smartspend"
      # alembic logs progress on stderr; Windows PowerShell would treat that as a failure under "Stop".
      $ErrorActionPreference = "Continue"
      $sql = & $Python -m alembic upgrade head --sql 2>$null
      $ErrorActionPreference = "Stop"
      if ($LASTEXITCODE -ne 0) { throw "alembic failed" }
    } finally { $env:DATABASE_URL = $saved; Pop-Location }
    $header = @(
      "-- SmartSpend: complete database schema (PostgreSQL 14+), generated from the Alembic migrations.",
      "-- Do not edit by hand: change a migration, then run  .\database\scripts\db.ps1 schema",
      "-- Load into an empty database:  psql -d smartspend -v ON_ERROR_STOP=1 -f database/01_schema.sql",
      "-- Generated $(Get-Date -Format 'yyyy-MM-dd HH:mm')",
      ""
    )
    # UTF-8 without a byte-order mark: psql would read a BOM as part of the first statement.
    [IO.File]::WriteAllLines($out, [string[]]($header + $sql), (New-Object Text.UTF8Encoding($false)))
    Write-Host "Wrote $out"
  }
  "backup" {
    $dir = Join-Path $Root "database\backups"
    New-Item -ItemType Directory -Force $dir | Out-Null
    $target = if ($File) { $File } else { Join-Path $dir ("smartspend-{0}.dump" -f (Get-Date -Format "yyyyMMdd-HHmm")) }
    & (Get-Tool "pg_dump") --format=custom --no-owner --file=$target (Get-Url)
    if ($LASTEXITCODE -ne 0) { throw "pg_dump failed" }
    Write-Host "Backup written to $target"
  }
  "restore" {
    if (-not $File -or -not (Test-Path $File)) { throw "Give the backup file to restore, e.g. database\backups\smartspend-20261022-1530.dump" }
    Write-Warning "This replaces every SmartSpend table in the target database with the backup's contents."
    $answer = Read-Host "Type RESTORE to continue"
    if ($answer -ne "RESTORE") { Write-Host "Cancelled."; return }
    & (Get-Tool "pg_restore") --clean --if-exists --no-owner --single-transaction --dbname=(Get-Url) $File
    if ($LASTEXITCODE -ne 0) { throw "pg_restore failed" }
    Write-Host "Restored $File. Restart the API so it reconnects."
  }
}
