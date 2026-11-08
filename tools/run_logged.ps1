# PATT-PDF retest helper for PowerShell 7 (Windows). Dot-source it:  . .\tools\run_logged.ps1
# Usage:  Run <name> <command> [arguments...]
# Writes all output of <command> to "$T\logs\<name>.txt" FIRST, then reads the real exit code,
# appends "<name> <code>" to "$T\logs\_exitcodes.txt" and shows the last 25 log lines.
#
# Fixes the v0.3.5 retest finding: the old wrapper did `$cmd, $rest = $args`; with exactly one
# argument after the command, $rest was a plain string and `@rest` splatted it character by
# character. The argument list is now always an array. Also handled: commands that cannot be
# started (exit code "start-failed" instead of a stale $LASTEXITCODE from an earlier command),
# PowerShell cmdlets (no $LASTEXITCODE: 0 or 1 from $?), arguments with spaces and Chinese
# characters (each array element is passed as one argument), and callers that pipe the output into
# `Select-Object -First n` (the exit code is recorded before any output).
# A plain function on purpose: an advanced function would try to bind "-m", "-q", "-N…" itself.
function Run {
  if ($args.Count -lt 2) { throw "usage: Run <name> <command> [arguments...]" }
  $Name = [string]$args[0]
  $Command = $args[1]
  $Rest = @($args | Select-Object -Skip 2)
  $log = Join-Path (Join-Path $T "logs") "$Name.txt"
  New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
  $global:LASTEXITCODE = $null
  $ok = $false; $started = $true
  if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
    $started = $false
    "RUN-WRAPPER: command not found: $Command" | Set-Content -LiteralPath $log -Encoding utf8
  } else {
    try {
      & $Command @Rest *> $log
      $ok = $?
    } catch {
      $started = $false
      "RUN-WRAPPER: could not start '$Command': $($_.Exception.Message)" | Add-Content -LiteralPath $log -Encoding utf8
    }
  }
  if (-not $started) { $rc = 'start-failed' }
  elseif ($null -ne $global:LASTEXITCODE) { $rc = $global:LASTEXITCODE }
  else { $rc = if ($ok) { 0 } else { 1 } }
  # record the exit code BEFORE emitting anything: a caller piping into `Select-Object -First n`
  # stops this function as soon as it has enough lines (found while testing this wrapper)
  "$Name $rc" | Add-Content -LiteralPath (Join-Path (Join-Path $T 'logs') '_exitcodes.txt') -Encoding utf8
  "[$Name] exit=$rc   (log: `$T\logs\$Name.txt)"
  Get-Content -LiteralPath $log -Tail 25 -ErrorAction SilentlyContinue
}
