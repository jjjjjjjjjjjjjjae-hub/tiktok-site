import { createServer } from 'node:http';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import worker from '../auth-worker/src/worker.js';
import { openDatabase } from './database.mjs';
import { loadConfig, projectRoot } from './config.mjs';
import { telegramClient, preparePolling, pollTelegram } from './telegram.mjs';

export function createApplication(config) {
  const db = openDatabase(config.dataDirectory);
  const env = {
    DB: db, TELEGRAM_BOT_TOKEN: config.token, ADMIN_TELEGRAM_ID: config.adminId,
    INVITE_ENCRYPTION_KEY: db.getState('INVITE_ENCRYPTION_KEY'),
    SESSION_SIGNING_KEY: db.getState('SESSION_SIGNING_KEY'),
    TELEGRAM_WEBHOOK_SECRET: db.getState('TELEGRAM_WEBHOOK_SECRET')
  };
  // Only these public files can be served. Config, source, database and .git are unreachable.
  const files = new Map([
    ['/', readFileSync(join(projectRoot, 'index.html'))],
    ['/index.html', readFileSync(join(projectRoot, 'index.html'))],
    ['/stadium.html', readFileSync(join(projectRoot, 'stadium.html'))]
  ]);
  let telegramState = config.noBot ? 'disabled' : 'starting';
  const rateLimits = new Map();
  const server = createServer(async (incoming, outgoing) => {
    outgoing.setHeader('X-Content-Type-Options', 'nosniff');
    outgoing.setHeader('Cache-Control', 'no-store');
    outgoing.setHeader('Referrer-Policy', 'no-referrer');
    if (config.origins.has(incoming.headers.origin)) {
      outgoing.setHeader('Access-Control-Allow-Origin', incoming.headers.origin);
      outgoing.setHeader('Vary', 'Origin');
    }
    try {
      if (!config.origins.has(`http://${incoming.headers.host}`) && !config.origins.has(`https://${incoming.headers.host}`)) { outgoing.writeHead(403); outgoing.end('Host not allowed'); return; }
      const url = new URL(incoming.url, `http://${incoming.headers.host}`);
      if (incoming.method === 'GET' && url.pathname === '/health') {
        outgoing.setHeader('Content-Type', 'application/json; charset=utf-8');
        outgoing.end(JSON.stringify({ ok: true, service: 'almas-node', version: 2, telegram: telegramState })); return;
      }
      if (incoming.method === 'GET' && url.pathname === '/app-config.js') {
        outgoing.setHeader('Content-Type', 'text/javascript; charset=utf-8');
        outgoing.end('window.ALMAS_CONFIG=Object.freeze({apiBase:window.location.origin,appVersion:"1.2.0"});'); return;
      }
      if (incoming.method === 'GET' && files.has(url.pathname)) {
        outgoing.setHeader('Content-Type', 'text/html; charset=utf-8');
        outgoing.end(files.get(url.pathname)); return;
      }
      if (!url.pathname.startsWith('/api/')) { outgoing.writeHead(404); outgoing.end('Not found'); return; }
      if (!['POST', 'OPTIONS'].includes(incoming.method)) { outgoing.writeHead(405); outgoing.end('Method not allowed'); return; }
      const origin = incoming.headers.origin || '';
      if (!config.origins.has(origin)) { outgoing.writeHead(403); outgoing.end('Origin not allowed'); return; }
      if (incoming.method === 'POST') {
        const now = Date.now(), ip = incoming.socket.remoteAddress;
        for (const [key, entry] of rateLimits) if (entry.until <= now) rateLimits.delete(key);
        const entry = rateLimits.get(ip) || { count: 0, until: now + 60000 };
        entry.count += 1; rateLimits.set(ip, entry);
        if (entry.count > 120) { outgoing.writeHead(429, { 'Retry-After': '60' }); outgoing.end('Too many requests'); return; }
      }
      let length = 0; const chunks = [];
      for await (const chunk of incoming) {
        length += chunk.length;
        if (length > 50000) { outgoing.writeHead(413); outgoing.end('Request too large'); return; }
        chunks.push(chunk);
      }
      const headers = { 'Content-Type': incoming.headers['content-type'] || '', Origin: origin };
      const request = new Request(url, { method: incoming.method, headers, ...(incoming.method === 'POST' ? { body: Buffer.concat(chunks) } : {}) });
      const response = await worker.fetch(request, { ...env, APP_ORIGIN: origin });
      outgoing.writeHead(response.status, Object.fromEntries(response.headers));
      outgoing.end(Buffer.from(await response.arrayBuffer()));
    } catch {
      if (!outgoing.headersSent) outgoing.writeHead(500, { 'Content-Type': 'application/json' });
      outgoing.end(JSON.stringify({ ok: false, message: 'Серверде қате шықты.' }));
    }
  });
  server.requestTimeout = 15000;
  server.headersTimeout = 10000;
  return { server, env, db, setTelegramState(value) { telegramState = value; } };
}

export async function main() {
  if (Number(process.versions.node.split('.')[0]) < 24) throw new Error('Node.js 24 or newer is required.');
  const config = loadConfig();
  const app = createApplication(config);
  if (process.argv.includes('--check')) { app.db.close(); console.log('CHECK OK: Node, config and database are ready.'); return; }
  try {
    await new Promise((resolve, reject) => { app.server.once('error', reject); app.server.listen(config.port, config.host, resolve); });
  } catch (error) {
    app.db.close();
    throw new Error(error.code === 'EADDRINUSE' ? 'Port is busy. Close the other server or set PORT=8081 in your config.' : 'The server could not start.');
  }
  const controller = new AbortController();
  let polling;
  const stop = async () => {
    if (controller.signal.aborted) return;
    controller.abort();
    app.server.closeAllConnections();
    await new Promise(resolve => app.server.close(resolve));
    await polling;
    app.db.close();
  };
  process.once('SIGINT', stop);
  process.once('SIGTERM', stop);
  console.log(`\nALMAS PROJEKT\nLaptop: http://localhost:${config.port}/`);
  for (const ip of config.localAddresses) console.log(`Phone (same Wi-Fi): http://${ip}:${config.port}/`);
  if (config.publicUrl) console.log(`Public: ${config.publicUrl}/`);
  console.log('Keep this window open. Ctrl+C stops the server.');
  if (config.openBrowser && process.platform === 'win32') {
    spawn('explorer.exe', [`http://localhost:${config.port}/`], { detached: true, stdio: 'ignore' }).on('error', () => {}).unref();
  }
  if (!config.noBot) {
    const call = telegramClient(config.token);
    try {
      const identity = await preparePolling(call, config.takeOverWebhook, controller.signal);
      if (controller.signal.aborted) return;
      app.setTelegramState('connected');
      console.log(`Telegram: @${identity.username}. Send /new Player_Name in your private chat with the bot.`);
      polling = pollTelegram({ call, env: app.env, db: app.db, signal: controller.signal, onState: app.setTelegramState });
    } catch (error) {
      app.setTelegramState('stopped');
      if (!controller.signal.aborted) console.log(error.message);
    }
  } else console.log('Telegram is disabled (--no-bot). Existing accounts can still log in.');
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(error => { console.error(error.message); process.exitCode = 1; });
}
