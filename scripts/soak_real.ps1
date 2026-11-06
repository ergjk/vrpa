# 真实机浸泡脚本（只读 dry-run，不会真实发送）
#
# 用法（管理员 PowerShell）：
#   .\scripts\soak_real.ps1                          # 20 轮，每轮间隔 20s
#   .\scripts\soak_real.ps1 -Iterations 5 -IntervalSeconds 15
#   .\scripts\soak_real.ps1 -Chat "王衢665" -Warmup 8 -Settle 3
#   .\scripts\soak_real.ps1 -DryRun                  # 只打印命令，不启动微信
#
# 说明：
#   - 每轮执行 `run --real --multi`，默认 dry_run=true，不会真实发送；
#   - 新消息需要大号发送；不发也可以验证重复轮次稳定性；
#   - 日志：data\soak_real\soak_<时间>.jsonl、stderr_<时间>.log、summary_<时间>.md
#   - 任一轮 ok=false 或 failures>0 立即停止并返回退出码 1。

param(
    [string]$Chat = "王衢665",
    [int]$Iterations = 20,
    [int]$IntervalSeconds = 20,
    [int]$Warmup = 8,
    [double]$Settle = 3,
    [string]$Python = "",
    [string]$Config = "",
    [string]$LogDir = "data\soak_real",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Invoke-PythonProcess {
    param([string]$FilePath, [string[]]$Arguments)
    $quoted = foreach ($arg in $Arguments) {
        if ($arg -match '[\s"]') { '"' + ($arg -replace '"', '\"') + '"' } else { $arg }
    }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $psi.Arguments = ($quoted -join ' ')
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    [void]$proc.Start()
    $stdout = $proc.StandardOutput.ReadToEnd()
    $stderr = $proc.StandardError.ReadToEnd()
    $proc.WaitForExit()
    return [pscustomobject]@{ ExitCode = $proc.ExitCode; StdOut = $stdout; StdErr = $stderr }
}

$root = Split-Path -Parent $PSScriptRoot

if (-not $Python) {
    $candidate = Join-Path $root "venv\Scripts\python.exe"
    if (Test-Path $candidate) { $Python = $candidate } else { $Python = "python" }
}
if ($Iterations -lt 1) { throw "Iterations 必须 >= 1" }
if ($IntervalSeconds -lt 0) { throw "IntervalSeconds 不能为负" }

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$jsonl = Join-Path $LogDir "soak_$stamp.jsonl"
$stderrLog = Join-Path $LogDir "stderr_$stamp.log"
$summary = Join-Path $LogDir "summary_$stamp.md"

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin) {
    Write-Warning "当前不是管理员 PowerShell；真机鼠标注入可能失败，建议以管理员身份运行。"
}

Write-Host "python   : $Python"
Write-Host "chat     : $Chat"
Write-Host "iterations: $Iterations   interval: ${IntervalSeconds}s"
Write-Host "log      : $jsonl"
Write-Host ""

$results = @()
$startedAt = Get-Date
$failed = $false

for ($i = 1; $i -le $Iterations; $i++) {
    Write-Host ("[{0}/{1}] {2} 开始" -f $i, $Iterations, (Get-Date -Format "HH:mm:ss"))
    $dump = Join-Path $LogDir ("raw_{0:00}.txt" -f $i)
    $runArgs = @(
        "-m", "wechat_agent", "run", "--real", "--chat", $Chat,
        "--ticks", "1", "--warmup", $Warmup, "--settle", $Settle,
        "--multi", "--dump", $dump, "--json"
    )
    if ($Config) { $runArgs += @("--config", $Config) }

    if ($DryRun) {
        Write-Host ("DRY-RUN: {0} {1}" -f $Python, ($runArgs -join " "))
        continue
    }

    $proc = Invoke-PythonProcess -FilePath $Python -Arguments $runArgs
    $out = $proc.StdOut
    $exitCode = $proc.ExitCode
    if ($proc.StdErr) {
        Add-Content -Path $stderrLog -Value $proc.StdErr -Encoding UTF8
    }
    $trimmed = $out.Trim()
    try {
        if (-not $trimmed) { throw "空输出" }
        $obj = $trimmed | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        Write-Host ("[{0}] JSON 解析失败：{1}" -f $i, $_.Exception.Message) -ForegroundColor Red
        $failed = $true
        break
    }

    $obj | Add-Member -NotePropertyName iteration -NotePropertyValue $i -Force
    $obj | ConvertTo-Json -Compress -Depth 12 | Add-Content -Path $jsonl -Encoding UTF8
    $results += $obj

    $replies = 0
    if ($null -ne $obj.replies) { $replies = @($obj.replies).Count }
    Write-Host ("[{0}] captured={1} ingested={2} duplicates={3} replies={4} writes={5} failures={6}" -f `
        $i, $obj.captured, $obj.ingested, $obj.duplicates, $replies, $obj.writes, $obj.failures)

    if ($exitCode -ne 0 -or -not $obj.ok -or $obj.failures -gt 0) {
        Write-Host ("[{0}] 失败：exit={1} ok={2} failures={3}" -f $i, $exitCode, $obj.ok, $obj.failures) -ForegroundColor Red
        $failed = $true
        break
    }

    if ($i -lt $Iterations) { Start-Sleep -Seconds $IntervalSeconds }
}

if ($DryRun) {
    Write-Host ""
    Write-Host "DryRun 完成：未启动微信、未写入 JSONL。"
    exit 0
}

$done = $results.Count
$okCount = @($results | Where-Object { $_.ok }).Count
$sumCaptured = ($results | Measure-Object -Property captured -Sum).Sum
$sumIngested = ($results | Measure-Object -Property ingested -Sum).Sum
$sumDuplicates = ($results | Measure-Object -Property duplicates -Sum).Sum
$sumWrites = ($results | Measure-Object -Property writes -Sum).Sum
$avgTotal = 0
if ($done -gt 0) {
    $avgTotal = [math]::Round((($results | ForEach-Object { $_.timing.total_ms }) | Measure-Object -Average).Average, 1)
}
$duration = (Get-Date) - $startedAt

$lines = @(
    "# 真实机浸泡汇总",
    "",
    "- 开始时间：$($startedAt.ToString('yyyy-MM-dd HH:mm:ss'))",
    "- 结束时间：$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))",
    "- 持续：$([math]::Round($duration.TotalMinutes, 1)) 分钟",
    "- Chat：$Chat",
    "- 计划轮数：$Iterations；完成：$done；成功：$okCount；失败：$($done - $okCount)",
    "- 汇总：captured=$sumCaptured ingested=$sumIngested duplicates=$sumDuplicates writes=$sumWrites",
    "- 平均单轮总耗时：$avgTotal ms",
    "- JSONL：$jsonl",
    "",
    "## 每轮",
    ""
)
foreach ($row in $results) {
    $replies = 0
    if ($null -ne $row.replies) { $replies = @($row.replies).Count }
    $lines += "- #$($row.iteration) ok=$($row.ok) captured=$($row.captured) ingested=$($row.ingested) duplicates=$($row.duplicates) replies=$replies writes=$($row.writes) failures=$($row.failures) total_ms=$($row.timing.total_ms)"
}
$lines | Set-Content -Path $summary -Encoding UTF8

Write-Host ""
Write-Host "浸泡完成：$done/$Iterations 轮，成功 $okCount，失败 $($done - $okCount)"
Write-Host "汇总 : $summary"
Write-Host "日志 : $jsonl"
if ($failed -or $done -lt $Iterations -or $okCount -ne $done) { exit 1 }
exit 0
