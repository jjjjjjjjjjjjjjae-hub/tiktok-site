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
        throw "$Name құпия мәнін сақтау сәтсіз аяқталды."
    }
}

if (-not (Test-Path "wrangler.toml")) {
    Write-Host "Алдымен wrangler.toml.example файлын wrangler.toml деп көшіріп, D1 database_id жазыңыз." -ForegroundColor Yellow
    exit 1
}

$tokenSecure = Read-Host "Telegram BotFather берген BOT TOKEN" -AsSecureString
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
    $typedAdminId = Read-Host "Табылған Telegram ID: $detectedAdminId. Қабылдау үшін Enter басыңыз"
    $adminId = if ([string]::IsNullOrWhiteSpace($typedAdminId)) {
        $detectedAdminId
    }
    else {
        $typedAdminId
    }
}
else {
    Write-Host "Ботқа /start жіберіп, скриптті қайта қоссаңыз ID автоматты табылады." -ForegroundColor Yellow
    $adminId = Read-Host "Өзіңіздің Telegram сандық ID"
}

if ($adminId -notmatch "^\d+$") {
    throw "Telegram ID тек сандардан тұруы керек."
}

$inviteKey = New-RandomSecret 32
$sessionKey = New-RandomSecret 32
$webhookSecret = New-RandomSecret 24

npx wrangler deploy --config wrangler.toml
if ($LASTEXITCODE -ne 0) {
    throw "Worker жарияланбады."
}

Set-WorkerSecret "TELEGRAM_BOT_TOKEN" $botToken
Set-WorkerSecret "ADMIN_TELEGRAM_ID" $adminId
Set-WorkerSecret "INVITE_ENCRYPTION_KEY" $inviteKey
Set-WorkerSecret "SESSION_SIGNING_KEY" $sessionKey
Set-WorkerSecret "TELEGRAM_WEBHOOK_SECRET" $webhookSecret

npx wrangler d1 execute almas-auth --remote --file schema.sql --config wrangler.toml
if ($LASTEXITCODE -ne 0) {
    throw "D1 кестелерін жасау сәтсіз аяқталды."
}

$workerUrl = (Read-Host "Жоғарыда шыққан Worker URL-ін жазыңыз").TrimEnd("/")
if ($workerUrl -notmatch "^https://") {
    throw "Worker URL https:// деп басталуы керек."
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
    throw "Telegram webhook қосылмады."
}

$botToken = $null
$tokenSecure.Dispose()
Write-Host ""
Write-Host "Дайын. Енді Worker URL-ін app-config.js ішіндегі apiBase жолына жазу керек:" -ForegroundColor Green
Write-Host $workerUrl -ForegroundColor Cyan
