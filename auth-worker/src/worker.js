const encoder = new TextEncoder();
const decoder = new TextDecoder();
const PASSWORD_ITERATIONS = 120000;
const INVITE_LIFETIME_SECONDS = 72 * 60 * 60;
const REGISTRATION_TICKET_SECONDS = 10 * 60;
const ACCESS_TOKEN_SECONDS = 12 * 60 * 60;

class HttpError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function base64UrlEncode(bytes) {
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function base64UrlDecode(value) {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized + "=".repeat((4 - normalized.length % 4) % 4);
  const binary = atob(padded);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

function randomToken(size = 32) {
  return base64UrlEncode(crypto.getRandomValues(new Uint8Array(size)));
}

async function sha256(value) {
  const bytes = typeof value === "string" ? encoder.encode(value) : value;
  return base64UrlEncode(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)));
}

function constantTimeEqual(left, right) {
  const a = typeof left === "string" ? encoder.encode(left) : left;
  const b = typeof right === "string" ? encoder.encode(right) : right;
  if (a.length !== b.length) return false;
  let difference = 0;
  for (let index = 0; index < a.length; index += 1) {
    difference |= a[index] ^ b[index];
  }
  return difference === 0;
}

function nowSeconds() {
  return Math.floor(Date.now() / 1000);
}

function changeCount(result) {
  return Number(result && result.meta && result.meta.changes) || 0;
}

function cleanPlayerName(value) {
  const name = String(value || "").trim();
  const allowed = /^[A-Za-zА-Яа-яЁёӘәІіҢңҒғҮүҰұҚқӨөҺһ][A-Za-zА-Яа-яЁёӘәІіҢңҒғҮүҰұҚқӨөҺһ0-9_]{2,15}$/u;
  if (!allowed.test(name)) {
    throw new HttpError(
      400,
      "INVALID_PLAYER_NAME",
      "Ат 3–16 таңба болуы, әріптен басталуы және тек әріп, сан, _ таңбасын қамтуы керек."
    );
  }
  return name;
}

function validDeviceId(value) {
  const deviceId = String(value || "");
  if (deviceId.length < 16 || deviceId.length > 256) {
    throw new HttpError(400, "INVALID_DEVICE", "Құрылғы анықталмады.");
  }
  return deviceId;
}

function validatePassword(password) {
  return typeof password === "string" &&
    password.length >= 8 &&
    password.length <= 32 &&
    /[a-z]/.test(password) &&
    /[A-Z]/.test(password) &&
    /[0-9]/.test(password) &&
    /[!@#$%^&*._-]/.test(password) &&
    !/\s/.test(password);
}

async function importAesKey(secret) {
  const raw = base64UrlDecode(String(secret || ""));
  if (raw.length !== 32) {
    throw new Error("INVITE_ENCRYPTION_KEY must contain 32 bytes.");
  }
  return crypto.subtle.importKey("raw", raw, "AES-GCM", false, ["encrypt", "decrypt"]);
}

async function encryptInvite(payload, secret) {
  const key = await importAesKey(secret);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = new Uint8Array(await crypto.subtle.encrypt(
    { name: "AES-GCM", iv },
    key,
    encoder.encode(JSON.stringify(payload))
  ));
  const packed = new Uint8Array(iv.length + ciphertext.length);
  packed.set(iv);
  packed.set(ciphertext, iv.length);
  return base64UrlEncode(packed);
}

async function decryptInvite(payload, secret) {
  try {
    const packed = base64UrlDecode(payload);
    if (packed.length < 29) throw new Error("short payload");
    const iv = packed.slice(0, 12);
    const ciphertext = packed.slice(12);
    const key = await importAesKey(secret);
    const plaintext = await crypto.subtle.decrypt({ name: "AES-GCM", iv }, key, ciphertext);
    return JSON.parse(decoder.decode(plaintext));
  } catch (_) {
    throw new HttpError(400, "INVALID_INVITE", "Шақыру файлы бүлінген немесе жалған.");
  }
}

async function derivePasswordHash(password, salt, iterations = PASSWORD_ITERATIONS) {
  const material = await crypto.subtle.importKey(
    "raw",
    encoder.encode(password),
    "PBKDF2",
    false,
    ["deriveBits"]
  );
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", hash: "SHA-256", salt, iterations },
    material,
    256
  );
  return new Uint8Array(bits);
}

async function createAccessToken(user, deviceHash, secret) {
  const issuedAt = nowSeconds();
  const payload = base64UrlEncode(encoder.encode(JSON.stringify({
    sub: user.id,
    name: user.player_name,
    device: deviceHash,
    iat: issuedAt,
    exp: issuedAt + ACCESS_TOKEN_SECONDS
  })));
  const key = await crypto.subtle.importKey(
    "raw",
    base64UrlDecode(String(secret || "")),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const signature = new Uint8Array(await crypto.subtle.sign("HMAC", key, encoder.encode(payload)));
  return payload + "." + base64UrlEncode(signature);
}

function corsHeaders(env, origin) {
  const allowedOrigin = String(env.APP_ORIGIN || "");
  const headers = {
    "Cache-Control": "no-store",
    "Content-Type": "application/json; charset=utf-8",
    "X-Content-Type-Options": "nosniff"
  };
  if (origin && origin === allowedOrigin) {
    headers["Access-Control-Allow-Origin"] = origin;
    headers.Vary = "Origin";
  }
  return headers;
}

function json(env, origin, body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: corsHeaders(env, origin)
  });
}

function requireAllowedOrigin(request, env) {
  const origin = request.headers.get("Origin") || "";
  if (!origin || origin !== String(env.APP_ORIGIN || "")) {
    throw new HttpError(403, "ORIGIN_BLOCKED", "Бұл сұрауға рұқсат жоқ.");
  }
  return origin;
}

async function readJson(request) {
  const text = await request.text();
  if (text.length > 50000) {
    throw new HttpError(413, "REQUEST_TOO_LARGE", "Сұрау тым үлкен.");
  }
  try {
    return JSON.parse(text);
  } catch (_) {
    throw new HttpError(400, "INVALID_JSON", "Дерек форматы дұрыс емес.");
  }
}

async function issueRegistrationTicket(env, userId) {
  const raw = randomToken(32);
  const tokenHash = await sha256(raw);
  const expiresAt = nowSeconds() + REGISTRATION_TICKET_SECONDS;
  await env.DB.batch([
    env.DB.prepare("DELETE FROM registration_tickets WHERE user_id = ?").bind(userId),
    env.DB.prepare(
      "INSERT INTO registration_tickets (token_hash, user_id, expires_at, consumed_at) VALUES (?, ?, ?, NULL)"
    ).bind(tokenHash, userId, expiresAt)
  ]);
  return raw;
}

async function redeemInvite(request, env, origin) {
  const body = await readJson(request);
  const outer = body.invite;
  if (!outer ||
      outer.format !== "almasinvite" ||
      outer.version !== 1 ||
      typeof outer.payload !== "string" ||
      outer.payload.length > 8192) {
    throw new HttpError(400, "INVALID_INVITE", "Бұл almas projekt шақыру файлы емес.");
  }

  const deviceId = validDeviceId(body.deviceId);
  const deviceHash = await sha256(deviceId);
  const payload = await decryptInvite(outer.payload, env.INVITE_ENCRYPTION_KEY);
  const currentTime = nowSeconds();

  if (payload.version !== 1 ||
      typeof payload.inviteId !== "string" ||
      typeof payload.token !== "string" ||
      !Number.isInteger(payload.expiresAt) ||
      payload.expiresAt <= currentTime) {
    throw new HttpError(410, "INVITE_EXPIRED", "Шақыру мерзімі аяқталған.");
  }

  const tokenHash = await sha256(payload.token);
  const invite = await env.DB.prepare(
    "SELECT id, token_hash, player_name, expires_at, used_at, used_device_hash FROM invites WHERE id = ?"
  ).bind(payload.inviteId).first();

  if (!invite ||
      !constantTimeEqual(String(invite.token_hash), tokenHash) ||
      Number(invite.expires_at) <= currentTime) {
    throw new HttpError(400, "INVALID_INVITE", "Шақыру жарамсыз немесе мерзімі аяқталған.");
  }

  let user;
  if (invite.used_at) {
    user = await env.DB.prepare(
      "SELECT id, player_name, status, device_hash FROM users WHERE invite_id = ?"
    ).bind(invite.id).first();

    if (!user ||
        user.status !== "pending" ||
        !constantTimeEqual(String(invite.used_device_hash || ""), deviceHash) ||
        !constantTimeEqual(String(user.device_hash || ""), deviceHash)) {
      throw new HttpError(409, "INVITE_USED", "Бұл файл бұрын қолданылған.");
    }
  } else {
    const userId = crypto.randomUUID();
    const batch = await env.DB.batch([
      env.DB.prepare(
        "UPDATE invites SET used_at = ?, used_device_hash = ? " +
        "WHERE id = ? AND token_hash = ? AND used_at IS NULL AND expires_at > ?"
      ).bind(currentTime, deviceHash, invite.id, tokenHash, currentTime),
      env.DB.prepare(
        "INSERT INTO users " +
        "(id, player_name, invite_id, status, auth_method, device_hash, created_at, updated_at) " +
        "SELECT ?, player_name, id, 'pending', NULL, ?, ?, ? FROM invites " +
        "WHERE id = ? AND used_at = ? AND used_device_hash = ?"
      ).bind(
        userId,
        deviceHash,
        currentTime,
        currentTime,
        invite.id,
        currentTime,
        deviceHash
      )
    ]);

    if (changeCount(batch[0]) !== 1 || changeCount(batch[1]) !== 1) {
      const retryUser = await env.DB.prepare(
        "SELECT id, player_name, status, device_hash FROM users WHERE invite_id = ?"
      ).bind(invite.id).first();

      if (!retryUser ||
          retryUser.status !== "pending" ||
          !constantTimeEqual(String(retryUser.device_hash || ""), deviceHash)) {
        throw new HttpError(409, "INVITE_USED", "Бұл файл басқа құрылғыда қолданылған.");
      }
      user = retryUser;
    } else {
      user = { id: userId, player_name: invite.player_name, status: "pending", device_hash: deviceHash };
    }
  }

  const registrationTicket = await issueRegistrationTicket(env, user.id);
  return json(env, origin, {
    ok: true,
    registrationTicket,
    player: { id: user.id, name: user.player_name }
  });
}

async function registerUser(request, env, origin) {
  const body = await readJson(request);
  const ticket = String(body.registrationTicket || "");
  const authMethod = body.authMethod === "device" ? "device" :
    body.authMethod === "password" ? "password" : "";
  const deviceId = validDeviceId(body.deviceId);

  if (ticket.length < 32 || !authMethod) {
    throw new HttpError(400, "INVALID_REGISTRATION", "Тіркелу дерегі дұрыс емес.");
  }
  if (authMethod === "password" && !validatePassword(body.password)) {
    throw new HttpError(400, "WEAK_PASSWORD", "Құпиясөз барлық шартқа сай болуы керек.");
  }

  const currentTime = nowSeconds();
  const ticketHash = await sha256(ticket);
  const deviceHash = await sha256(deviceId);
  const record = await env.DB.prepare(
    "SELECT t.token_hash, t.user_id, t.expires_at, t.consumed_at, " +
    "u.id, u.player_name, u.status, u.device_hash " +
    "FROM registration_tickets t JOIN users u ON u.id = t.user_id " +
    "WHERE t.token_hash = ?"
  ).bind(ticketHash).first();

  if (!record ||
      record.consumed_at ||
      Number(record.expires_at) <= currentTime ||
      record.status !== "pending" ||
      !constantTimeEqual(String(record.device_hash || ""), deviceHash)) {
    throw new HttpError(401, "REGISTRATION_EXPIRED", "Тіркелу уақыты аяқталды. Файлды қайта таңдаңыз.");
  }

  let passwordSalt = null;
  let passwordHash = null;
  let passwordIterations = null;

  if (authMethod === "password") {
    const salt = crypto.getRandomValues(new Uint8Array(16));
    passwordSalt = base64UrlEncode(salt);
    passwordHash = base64UrlEncode(await derivePasswordHash(body.password, salt));
    passwordIterations = PASSWORD_ITERATIONS;
  }

  const deviceToken = randomToken(32);
  const deviceTokenHash = await sha256(deviceToken);
  const results = await env.DB.batch([
    env.DB.prepare(
      "UPDATE users SET status = 'active', auth_method = ?, password_salt = ?, " +
      "password_hash = ?, password_iterations = ?, device_token_hash = ?, " +
      "failed_attempts = 0, locked_until = NULL, updated_at = ? " +
      "WHERE id = ? AND status = 'pending'"
    ).bind(
      authMethod,
      passwordSalt,
      passwordHash,
      passwordIterations,
      deviceTokenHash,
      currentTime,
      record.id
    ),
    env.DB.prepare(
      "UPDATE registration_tickets SET consumed_at = ? " +
      "WHERE token_hash = ? AND consumed_at IS NULL"
    ).bind(currentTime, ticketHash)
  ]);

  if (changeCount(results[0]) !== 1 || changeCount(results[1]) !== 1) {
    throw new HttpError(409, "REGISTRATION_CONFLICT", "Тіркелу бұрын аяқталған.");
  }

  const user = { id: record.id, player_name: record.player_name };
  const accessToken = await createAccessToken(user, deviceHash, env.SESSION_SIGNING_KEY);
  return json(env, origin, {
    ok: true,
    player: { id: user.id, name: user.player_name },
    authMethod,
    deviceToken,
    accessToken
  });
}

async function getLoginUser(env, body) {
  const accountId = String(body.accountId || "");
  const deviceId = validDeviceId(body.deviceId);
  const deviceToken = String(body.deviceToken || "");
  if (!accountId || deviceToken.length < 32) {
    throw new HttpError(401, "SESSION_INVALID", "Құрылғы тіркелмеген.");
  }

  const deviceHash = await sha256(deviceId);
  const deviceTokenHash = await sha256(deviceToken);
  const user = await env.DB.prepare(
    "SELECT id, player_name, status, auth_method, password_salt, password_hash, " +
    "password_iterations, device_hash, device_token_hash, failed_attempts, locked_until " +
    "FROM users WHERE id = ?"
  ).bind(accountId).first();

  if (!user ||
      user.status !== "active" ||
      !constantTimeEqual(String(user.device_hash || ""), deviceHash) ||
      !constantTimeEqual(String(user.device_token_hash || ""), deviceTokenHash)) {
    throw new HttpError(401, "SESSION_INVALID", "Бұл аккаунт осы құрылғыға тіркелмеген.");
  }

  return { user, deviceHash };
}

async function loginWithDevice(request, env, origin) {
  const body = await readJson(request);
  const { user, deviceHash } = await getLoginUser(env, body);
  if (user.auth_method !== "device") {
    throw new HttpError(400, "WRONG_AUTH_METHOD", "Бұл аккаунт құпиясөзбен кіреді.");
  }

  const accessToken = await createAccessToken(user, deviceHash, env.SESSION_SIGNING_KEY);
  return json(env, origin, {
    ok: true,
    player: { id: user.id, name: user.player_name },
    authMethod: "device",
    accessToken
  });
}

async function loginWithPassword(request, env, origin) {
  const body = await readJson(request);
  const { user, deviceHash } = await getLoginUser(env, body);
  if (user.auth_method !== "password" || typeof body.password !== "string") {
    throw new HttpError(400, "WRONG_AUTH_METHOD", "Бұл аккаунт телефон құлпымен кіреді.");
  }

  const currentTime = nowSeconds();
  if (user.locked_until && Number(user.locked_until) > currentTime) {
    throw new HttpError(429, "LOGIN_LOCKED", "Қате әрекет көп. 5 минуттан кейін қайталаңыз.");
  }

  const salt = base64UrlDecode(user.password_salt);
  const actualHash = await derivePasswordHash(
    body.password,
    salt,
    Number(user.password_iterations) || PASSWORD_ITERATIONS
  );
  const valid = constantTimeEqual(actualHash, base64UrlDecode(user.password_hash));

  if (!valid) {
    const attempts = Number(user.failed_attempts || 0) + 1;
    const lockedUntil = attempts >= 5 ? currentTime + 300 : null;
    await env.DB.prepare(
      "UPDATE users SET failed_attempts = ?, locked_until = ?, updated_at = ? WHERE id = ?"
    ).bind(attempts >= 5 ? 0 : attempts, lockedUntil, currentTime, user.id).run();
    throw new HttpError(
      attempts >= 5 ? 429 : 401,
      attempts >= 5 ? "LOGIN_LOCKED" : "PASSWORD_INCORRECT",
      attempts >= 5 ? "Қате әрекет көп. 5 минуттан кейін қайталаңыз." : "Құпиясөз қате."
    );
  }

  await env.DB.prepare(
    "UPDATE users SET failed_attempts = 0, locked_until = NULL, updated_at = ? WHERE id = ?"
  ).bind(currentTime, user.id).run();

  const accessToken = await createAccessToken(user, deviceHash, env.SESSION_SIGNING_KEY);
  return json(env, origin, {
    ok: true,
    player: { id: user.id, name: user.player_name },
    authMethod: "password",
    accessToken
  });
}

async function telegramApi(env, method, options) {
  const response = await fetch(
    "https://api.telegram.org/bot" + env.TELEGRAM_BOT_TOKEN + "/" + method,
    options
  );
  const result = await response.json();
  if (!response.ok || !result.ok) {
    throw new Error("Telegram API request failed: " + method);
  }
  return result;
}

async function sendTelegramMessage(env, chatId, text) {
  return telegramApi(env, "sendMessage", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text })
  });
}

async function sendInviteDocument(env, chatId, playerName, inviteId, documentValue, expiresAt) {
  const safeName = playerName.replace(/[^\p{L}\p{N}_-]/gu, "_");
  const form = new FormData();
  form.append("chat_id", String(chatId));
  form.append(
    "document",
    new Blob([JSON.stringify(documentValue, null, 2)], {
      type: "application/vnd.almas.invite+json"
    }),
    safeName + ".almasinvite"
  );
  form.append(
    "caption",
    "Ойыншы: " + playerName + "\nID: " + inviteId + "\nЖарамдылық: " +
      new Date(expiresAt * 1000).toISOString().replace("T", " ").slice(0, 16) + " UTC"
  );
  return telegramApi(env, "sendDocument", { method: "POST", body: form });
}

async function createInvite(env, playerName, adminId) {
  const existing = await env.DB.prepare(
    "SELECT id FROM users WHERE player_name = ? AND status != 'blocked'"
  ).bind(playerName).first();
  if (existing) {
    throw new HttpError(409, "PLAYER_EXISTS", "Бұл ойыншы аты бұрын тіркелген.");
  }

  const inviteId = crypto.randomUUID();
  const token = randomToken(32);
  const tokenHash = await sha256(token);
  const createdAt = nowSeconds();
  const expiresAt = createdAt + INVITE_LIFETIME_SECONDS;

  await env.DB.prepare(
    "INSERT INTO invites " +
    "(id, token_hash, player_name, created_at, expires_at, used_at, used_device_hash, created_by_telegram_id) " +
    "VALUES (?, ?, ?, ?, ?, NULL, NULL, ?)"
  ).bind(inviteId, tokenHash, playerName, createdAt, expiresAt, String(adminId)).run();

  const encrypted = await encryptInvite({
    version: 1,
    inviteId,
    token,
    expiresAt
  }, env.INVITE_ENCRYPTION_KEY);

  return {
    inviteId,
    expiresAt,
    document: { format: "almasinvite", version: 1, payload: encrypted }
  };
}

async function handleTelegram(request, env) {
  const suppliedSecret = request.headers.get("X-Telegram-Bot-Api-Secret-Token") || "";
  if (!constantTimeEqual(suppliedSecret, String(env.TELEGRAM_WEBHOOK_SECRET || ""))) {
    return new Response("Forbidden", { status: 403 });
  }

  const update = await readJson(request);
  const message = update.message;
  if (!message || !message.text || !message.from) {
    return new Response("OK");
  }

  const senderId = String(message.from.id);
  const chatId = String(message.chat.id);
  if (!constantTimeEqual(senderId, String(env.ADMIN_TELEGRAM_ID || ""))) {
    return new Response("OK");
  }

  const text = String(message.text).trim();
  const command = text.match(/^\/new(?:@\w+)?\s+(.+)$/u);

  try {
    if (/^\/start(?:@\w+)?$/u.test(text)) {
      await sendTelegramMessage(
        env,
        chatId,
        "almas projekt бот дайын.\n\nШақыру жасау:\n/new Player_Name"
      );
    } else if (command) {
      const playerName = cleanPlayerName(command[1]);
      const invite = await createInvite(env, playerName, senderId);
      await sendInviteDocument(
        env,
        chatId,
        playerName,
        invite.inviteId,
        invite.document,
        invite.expiresAt
      );
    } else {
      await sendTelegramMessage(env, chatId, "Пәрмен: /new Player_Name");
    }
  } catch (error) {
    console.error("Telegram command failed", error && error.code ? error.code : "UNKNOWN");
    await sendTelegramMessage(
      env,
      chatId,
      error instanceof HttpError ? error.message : "Шақыру жасау кезінде қате шықты."
    );
  }

  return new Response("OK");
}

async function handleApi(request, env) {
  const origin = requireAllowedOrigin(request, env);
  const path = new URL(request.url).pathname;

  if (path === "/api/invites/redeem") return redeemInvite(request, env, origin);
  if (path === "/api/register") return registerUser(request, env, origin);
  if (path === "/api/login/password") return loginWithPassword(request, env, origin);
  if (path === "/api/login/device") return loginWithDevice(request, env, origin);
  throw new HttpError(404, "NOT_FOUND", "Мұндай сұрау жоқ.");
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const origin = request.headers.get("Origin") || "";

    if (request.method === "OPTIONS" && url.pathname.startsWith("/api/")) {
      if (origin !== String(env.APP_ORIGIN || "")) {
        return new Response(null, { status: 403 });
      }
      return new Response(null, {
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": origin,
          "Access-Control-Allow-Headers": "Content-Type",
          "Access-Control-Allow-Methods": "POST, OPTIONS",
          "Access-Control-Max-Age": "600",
          Vary: "Origin"
        }
      });
    }

    try {
      if (request.method === "GET" && url.pathname === "/health") {
        return json(env, origin, { ok: true, service: "almas-auth", version: 1 });
      }
      if (request.method === "POST" && url.pathname === "/telegram") {
        return handleTelegram(request, env);
      }
      if (request.method === "POST" && url.pathname.startsWith("/api/")) {
        return handleApi(request, env);
      }
      return new Response("Not found", { status: 404 });
    } catch (error) {
      if (error instanceof HttpError) {
        return json(env, origin, { ok: false, code: error.code, message: error.message }, error.status);
      }
      console.error("Unhandled worker error", error);
      return json(env, origin, {
        ok: false,
        code: "SERVER_ERROR",
        message: "Серверде қате шықты. Кейін қайталаңыз."
      }, 500);
    }
  }
};

