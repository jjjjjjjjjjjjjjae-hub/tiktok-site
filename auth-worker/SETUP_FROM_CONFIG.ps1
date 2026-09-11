param(
    [string]$ConfigPath = (Join-Path (Join-Path $env:USERPROFILE "Downloads") "BOT_CONFIG_LOCAL.txt")
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function New-RandomSecret {
    param([int]$ByteCount = 32)
    $bytes = New-Object byte[] $ByteCount
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    return [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

function Set-WorkerSecret {
    param([string]$Name, [string]$Value)
    $Value | npx wrangler secret put $Name --config wrangler.toml
    if ($LASTEXITCODE -ne 0) {
        throw "Could not store Worker secret: $Name"
    }
}

if (-not (Test-Path $ConfigPath)) {
    throw "Config file not found: $ConfigPath"
}
if (-not (Test-Path "wrangler.toml")) {
    throw "wrangler.toml is missing."
}
if (-not (Test-Path "schema.sql")) {
    throw "schema.sql is missing."
}

$settings = @{}
foreach ($line in Get-Content -LiteralPath $ConfigPath) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith("#")) {
        continue
    }
    $parts = $trimmed.Split(@("="), 2, [StringSplitOptions]::None)
    if ($parts.Count -eq 2) {
        $key = $parts[0].Trim().Trim([char]0xFEFF)
        $settings[$key] = $parts[1].Trim()
    }
}

$botToken = [string]$settings["TELEGRAM_BOT_TOKEN"]
$adminId = [string]$settings["ADMIN_TELEGRAM_ID"]

if ($botToken -notmatch "^\d+:[A-Za-z0-9_-]+$") {
    throw "TELEGRAM_BOT_TOKEN is empty or invalid."
}
if ($adminId -notmatch "^\d+$") {
    throw "ADMIN_TELEGRAM_ID must contain digits only."
}

Write-Host ""
Write-Host "Config loaded. Token and ID will not be printed." -ForegroundColor Green
Write-Host "If Cloudflare asks for a workers.dev subdomain:" -ForegroundColor Yellow
Write-Host "1. Press Y and Enter" -ForegroundColor Yellow
Write-Host "2. Type almasprojektkz and press Enter" -ForegroundColor Yellow
Write-Host ""

npx wrangler deploy --config wrangler.toml
if ($LASTEXITCODE -ne 0) {
    throw "Worker deployment stopped or failed."
}

$inviteKey = New-RandomSecret 32
$sessionKey = New-RandomSecret 32
$webhookSecret = New-RandomSecret 24

Set-WorkerSecret "TELEGRAM_BOT_TOKEN" $botToken
Set-WorkerSecret "ADMIN_TELEGRAM_ID" $adminId
Set-WorkerSecret "INVITE_ENCRYPTION_KEY" $inviteKey
Set-WorkerSecret "SESSION_SIGNING_KEY" $sessionKey
Set-WorkerSecret "TELEGRAM_WEBHOOK_SECRET" $webhookSecret

npx wrangler d1 execute almas-auth --remote --file schema.sql --config wrangler.toml
if ($LASTEXITCODE -ne 0) {
    throw "Could not create the D1 tables."
}

$workerUrl = "https://almas-auth.almasprojektkz.workers.dev"
$webhookUrl = "$workerUrl/telegram"
$telegramUrl = "https://api.telegram.org/bot$botToken/setWebhook"
$body = @{
    url = $webhookUrl
    secret_token = $webhookSecret
    drop_pending_updates = $true
} | ConvertTo-Json

$result = Invoke-RestMethod -Method Post -Uri $telegramUrl -ContentType "application/json" -Body $body
if (-not $result.ok) {
    throw "Telegram webhook could not be configured."
}

$botToken = $null
Write-Host ""
Write-Host "SETUP COMPLETE" -ForegroundColor Green
Write-Host "Worker URL: $workerUrl" -ForegroundColor Cyan
Write-Host "Delete BOT_CONFIG_LOCAL.txt after the site is connected." -ForegroundColor Yellow
