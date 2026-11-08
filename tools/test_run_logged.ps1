# Self-test of tools/run_logged.ps1 (PowerShell 7). Run:  pwsh -NoProfile -File tools/test_run_logged.ps1
# Exit 0 = all checks passed. Uses only a temporary folder; touches nothing else.
# Also checks that the OLD wrapper really had the single-argument bug (so the test can catch it).
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here 'run_logged.ps1')
$T = Join-Path ([IO.Path]::GetTempPath()) ("patt run 测试 " + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Force $T | Out-Null
$py = (Get-Command python3 -ErrorAction SilentlyContinue) ?? (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) { throw "python not found on PATH" }
$py = $py.Source
$fail = 0
function Check([string]$what, [bool]$cond) {
  if ($cond) { "PASS  $what" } else { "FAIL  $what"; $script:fail++ }
}
function Code([string]$name) {
  $line = Get-Content -LiteralPath (Join-Path (Join-Path $T 'logs') '_exitcodes.txt') | Where-Object { $_ -like "$name *" } | Select-Object -Last 1
  return $line.Substring($name.Length + 1)
}
function Log([string]$name) { Get-Content -LiteralPath (Join-Path (Join-Path $T "logs") "$name.txt") -Raw -Encoding utf8 }

$argv = 'import sys; print(repr(sys.argv[1:])); sys.exit(int(sys.argv[1]) if sys.argv[1:] and sys.argv[1].isdigit() else 0)'
$script = Join-Path $T 'argv.py'; Set-Content -LiteralPath $script -Value $argv -Encoding utf8

Run one $py --version | Out-Null
Check 'single argument is passed whole (not split into characters)' ((Code one) -eq '0' -and (Log one) -match 'Python 3\.')
Run multi $py $script 'a b' '报告 2026 – résumé.pdf' "$T\空格 目录" | Out-Null
Check 'several arguments, with spaces and Chinese, each stays one argument' ((Log multi) -match "\['a b', '报告 2026 – résumé.pdf', '.+空格 目录'\]")
Run nonzero $py $script 7 | Out-Null
Check 'non-zero exit code is recorded' ((Code nonzero) -eq '7')
Run zero-after $py $script 0 | Out-Null
Check 'exit 0 after a failing command is recorded as 0' ((Code zero-after) -eq '0')
Run missing 'patt-no-such-command-xyz' '--help' | Out-Null
Check 'a command that cannot be started is start-failed, not a stale code' ((Code missing) -eq 'start-failed' -and (Log missing) -match 'command not found')
$errpy = Join-Path $T 'err.py'
Set-Content -LiteralPath $errpy -Encoding utf8 -Value "import sys`nsys.stderr.write('to-stderr\n')`nprint('to-stdout')`nsys.exit(3)"
Run stderr $py $errpy | Out-Null
Check 'stdout and stderr both land in the log, exit 3' ((Code stderr) -eq '3' -and (Log stderr) -match 'to-stderr' -and (Log stderr) -match 'to-stdout')
Run cmdlet Get-ChildItem -LiteralPath $T | Out-Null
Check 'cmdlet without $LASTEXITCODE gives 0' ((Code cmdlet) -eq '0')
$tail = Run pipe2 $py $script 'xxx'
Check 'wrapper output can be captured/piped; log is written first' (($tail -join "`n") -match 'exit=0' -and (Log pipe2) -match 'xxx')

Run first-only $py $script 5 | Select-Object -First 1 | Out-Null
Check 'exit code is recorded even if the caller stops reading after one line' ((Code first-only) -eq '5')

# The old wrapper (as in the v0.3.5 prompt) must show the bug, otherwise this test proves nothing.
function OldRun([string]$Name) {
  $cmd, $rest = $args
  & $cmd @rest *> (Join-Path (Join-Path $T "logs") "$Name.txt"); $rc = $LASTEXITCODE
  "$Name $rc" | Add-Content (Join-Path (Join-Path $T 'logs') '_exitcodes.txt')
}
# (one argument = the script path; split into characters it is never run as a script. Do not use
# a flag such as --version here: its "-" becomes "read from stdin" and the old wrapper hangs.)
OldRun old-one $py $script
Check 'old wrapper reproduces the single-argument splat bug' ((Log old-one) -notmatch "\[\]")
Run new-one $py $script | Out-Null
Check 'new wrapper runs the same single-argument command correctly' ((Code new-one) -eq '0' -and (Log new-one) -match "\[\]")

"exit codes file:"; Get-Content -LiteralPath (Join-Path (Join-Path $T 'logs') '_exitcodes.txt')
Remove-Item -LiteralPath $T -Recurse -Force
if ($fail) { "$fail check(s) failed"; exit 1 } else { "all checks passed"; exit 0 }
