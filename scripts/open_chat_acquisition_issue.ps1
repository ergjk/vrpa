# 打开“聊天记录获取方法征集”预填 issue。
# 不依赖 gh/token；浏览器里登录 GitHub 后点 Submit 即可。
$ErrorActionPreference = "Stop"
$repo = "ergjk/vrpa"
$template = Join-Path $PSScriptRoot "..\.github\ISSUE_TEMPLATE\chat-acquisition.md"
$body = Get-Content -LiteralPath $template -Raw -Encoding UTF8
# 去掉 issue 模板的 YAML front matter，只把正文预填进 issue。
$body = [regex]::Replace($body, "(?s)^---.*?---\s*", "", 1)
$title = "[Acquisition] 聊天记录获取方法征集"
$url = "https://github.com/$repo/issues/new?title=" + [uri]::EscapeDataString($title) + "&body=" + [uri]::EscapeDataString($body)
Write-Host "Opening prefilled GitHub issue..."
Start-Process $url
