<#
.SYNOPSIS
  VRPA-WeChat-Agent 质量门禁（M0-F-01）。
.DESCRIPTION
  依次执行：ruff check -> ruff format --check -> mypy（vrpa 落地后）-> pytest(+coverage)。
  任一步非 0 即整体失败。门禁通过后由命令行执行 Git 提交（脚本本身不改动版本库）。
  注意：本文件以 UTF-8 BOM 保存，兼容 Windows PowerShell 5.1。
.PARAMETER Fix
  自动修复 ruff 可修复项并格式化代码。
.PARAMETER NoCoverage
  跳过覆盖率统计（本地快速反馈）。
#>
[CmdletBinding()]
param(
    [switch]$Fix,
    [switch]$NoCoverage
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$python = Join-Path $repoRoot 'venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }

$script:failures = @()

function Invoke-Step {
    param([string]$Name, [scriptblock]$Body)
    Write-Host ''
    Write-Host "=== $Name ===" -ForegroundColor Cyan
    & $Body
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        $script:failures += $Name
        Write-Host "[FAIL] $Name (exit=$code)" -ForegroundColor Red
    } else {
        Write-Host "[OK] $Name" -ForegroundColor Green
    }
}

$ruffArgs = @('-m', 'ruff', 'check', '.')
if ($Fix) { $ruffArgs = @('-m', 'ruff', 'check', '--fix', '.') }
Invoke-Step 'ruff check' { & $python @ruffArgs }

$formatArgs = @('-m', 'ruff', 'format', '--check', '.')
if ($Fix) { $formatArgs = @('-m', 'ruff', 'format', '.') }
Invoke-Step 'ruff format' { & $python @formatArgs }

if (Test-Path (Join-Path $repoRoot 'vrpa')) {
    Invoke-Step 'mypy (vrpa strict)' { & $python -m mypy }
} else {
    Write-Host ''
    Write-Host '=== mypy ===' -ForegroundColor Cyan
    Write-Host '[SKIP] vrpa 尚未落地（F-02 起强制 strict）' -ForegroundColor Yellow
}

if ($NoCoverage) {
    Invoke-Step 'pytest' { & $python -m pytest tests -q }
} else {
    $covArgs = @()
    foreach ($pkg in @('wechat_agent', 'vrpa')) {
        if (Test-Path (Join-Path $repoRoot $pkg)) { $covArgs += "--cov=$pkg" }
    }
    Invoke-Step 'pytest + coverage' {
        & $python -m pytest tests -q @covArgs --cov-report=term-missing
    }
}

Write-Host ''
if ($script:failures.Count -gt 0) {
    Write-Host ('QUALITY GATE: FAIL -> ' + ($script:failures -join ', ')) -ForegroundColor Red
    exit 1
}
Write-Host 'QUALITY GATE: PASS' -ForegroundColor Green
exit 0