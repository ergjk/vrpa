# GitHub 仓库信息一键配置：About / Topics / labels
# 前置：先执行一次登录（任选其一）
#   .\data\tools\gh\bin\gh.exe auth login
#   或 $env:GH_TOKEN = "ghp_xxx"（不要提交到仓库）
#
# 然后运行：
#   .\scripts\github_setup.ps1
# 预览不写入：
#   .\scripts\github_setup.ps1 -DryRun

param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$gh = Join-Path $root "data\tools\gh\bin\gh.exe"

if (-not (Test-Path $gh)) {
    $found = Get-Command gh -ErrorAction SilentlyContinue
    if ($null -eq $found) {
        Write-Host "未找到 gh：请先下载 GitHub CLI 或运行 scripts/github_setup.py --gh <gh.exe>"
        exit 1
    }
    $gh = $found.Source
}

Write-Host "gh = $gh"
& $gh auth status 2>&1 | Out-String | Write-Host
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "尚未登录 GitHub，请先执行（只需一次）："
    Write-Host "  $gh auth login"
    Write-Host "选择：GitHub.com -> HTTPS -> Login with a web browser -> 输入显示的 code"
    Write-Host "或设置环境变量 GH_TOKEN 后重试。"
    exit 1
}

$py = Join-Path $root "venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$argsList = @((Join-Path $root "scripts\github_setup.py"), "--gh", $gh)
if ($DryRun) { $argsList += "--dry-run" }
& $py @argsList
exit $LASTEXITCODE
