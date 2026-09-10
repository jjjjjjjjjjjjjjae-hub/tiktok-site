$ErrorActionPreference = "Stop"

function ConvertTo-PlainText {
    param([Security.SecureString]$SecureValue)
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

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

if (-not (Test-Path "wrangler.toml")) {
    Write-Host "Missing wrangler.toml. Copy wrangler.toml.example and add the D1 database_id first." -ForegroundColor Yellow
    exit 1
}

$tokenSecure = Read-Host "Telegram BOT TOKEN (input is hidden)" -AsSecureString
$botToken = ConvertTo-PlainText $tokenSecure

$detectedAdminId = $null
try {
    $updates = Invoke-RestMethod -Method Get -Uri "https://api.telegram.org/bot$botToken/getUpdates"
    $lastMessage = $updates.result |
        Where-Object { $_.message -and $_.message.from -and $_.message.from.id } |
        Select-Object -Last 1
    if ($lastMessage) {
        $detectedAdminId = [string]$lastMessage.message.from.id
    }
}
catch {
    $detectedAdminId = $null
}

if ($detectedAdminId) {
    $typedAdminId = Read-Host "Detected Telegram ID: $detectedAdminId. Press Enter to accept or type another ID"
    $adminId = if ([string]::IsNullOrWhiteSpace($typedAdminId)) {
        $detectedAdminId
    }
    else {
        $typedAdminId
    }
}
else {
    Write-Host "Send /start to your bot. You may also enter the numeric ID manually now." -ForegroundColor Yellow
    $adminId = Read-Host "Your numeric Telegram ID"
}

if ($adminId -notmatch "^\d+$") {
    throw "Telegram ID must contain digits only."
}

$inviteKey = New-RandomSecret 32
$sessionKey = New-RandomSecret 32
$webhookSecret = New-RandomSecret 24

npx wrangler deploy --config wrangler.toml
if ($LASTEXITCODE -ne 0) {
    throw "Worker deployment failed."
}

Set-WorkerSecret "TELEGRAM_BOT_TOKEN" $botToken
Set-WorkerSecret "ADMIN_TELEGRAM_ID" $adminId
Set-WorkerSecret "INVITE_ENCRYPTION_KEY" $inviteKey
Set-WorkerSecret "SESSION_SIGNING_KEY" $sessionKey
Set-WorkerSecret "TELEGRAM_WEBHOOK_SECRET" $webhookSecret

npx wrangler d1 execute almas-auth --remote --file schema.sql --config wrangler.toml
if ($LASTEXITCODE -ne 0) {
    throw "Could not create the D1 tables."
}

$workerUrl = (Read-Host "Paste the Worker URL printed above").TrimEnd("/")
if ($workerUrl -notmatch "^https://") {
    throw "Worker URL must start with https://"
}

$webhookUrl = "$workerUrl/telegram"
$telegramUrl = "https://api.telegram.org/bot$botToken/setWebhook"
$body = @{
    url = $webhookUrl
    secret_token = $webhookSecret
    drop_pending_updates = $true
} | ConvertTo-Json

$result = Invoke-RestMethod -Method Post -Uri $telegramUrl -ContentType "application/json" -Body $body
if (-not $result.ok) {
    throw "Telegram webhook setup failed."
}

$botToken = $null
$tokenSecure.Dispose()
Write-Host ""
Write-Host "Setup complete. Put this Worker URL into app-config.js apiBase:" -ForegroundColor Green
Write-Host $workerUrl -ForegroundColor Cyan
