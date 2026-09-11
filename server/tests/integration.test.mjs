import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { request as httpRequest } from 'node:http';
import worker from '../../auth-worker/src/worker.js';
import { createApplication } from '../index.mjs';
import { parseConfig } from '../config.mjs';
import { telegramClient, preparePolling, pollTelegram } from '../telegram.mjs';

const realFetch = globalThis.fetch;
const testToken = '123456789:TEST_ONLY_not_a_real_telegram_token';
const deviceA = 'test-device-alpha-0001';
const deviceB = 'test-device-bravo-0002';
const password = 'TestPass123!';

async function fixture(t) {
  const directory = mkdtempSync(join(tmpdir(), 'almas-test-'));
  const config = { dataDirectory: directory, token: testToken, adminId: '42', noBot: true, origins: new Set() };
  let closed = false;
  const context = { documents: [], messages: [], failDocument: false };
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.ok(String(url).startsWith(`https://api.telegram.org/bot${testToken}/`), 'No real network calls from the Telegram handler');
    if (String(url).endsWith('/sendDocument')) {
      if (context.failDocument) return Response.json({ ok: false }, { status: 503 });
      assert.equal(options.body.get('chat_id'), '42');
      context.documents.push(JSON.parse(await options.body.get('document').text()));
    } else if (String(url).endsWith('/sendMessage')) context.messages.push(JSON.parse(options.body));
    else assert.fail('Unexpected Telegram API method');
    return Response.json({ ok: true, result: { message_id: 1 } });
  });
  context.start = async () => {
    closed = false;
    context.app = createApplication(config);
    await new Promise(resolve => context.app.server.listen(0, '127.0.0.1', resolve));
    context.origin = `http://127.0.0.1:${context.app.server.address().port}`;
    config.origins.add(context.origin);
  };
  context.close = async () => {
    if (closed) return;
    closed = true;
    context.app.server.closeAllConnections();
    await new Promise(resolve => context.app.server.close(resolve));
    context.app.db.close();
  };
  t.after(async () => { await context.close(); rmSync(directory, { recursive: true, force: true }); });
  await context.start();
  context.api = async (path, body, origin = context.origin) => {
    const response = await realFetch(context.origin + path, {
      method: 'POST', headers: { Origin: origin, 'Content-Type': 'application/json' }, body: JSON.stringify(body)
    });
    const raw = await response.text();
    let data; try { data = JSON.parse(raw); } catch { data = raw; }
    return { status: response.status, data };
  };
  context.telegram = (name, updateId, extra = {}) => worker.fetch(new Request('http://internal/telegram', {
    method: 'POST', headers: { 'X-Telegram-Bot-Api-Secret-Token': context.app.env.TELEGRAM_WEBHOOK_SECRET },
    body: JSON.stringify({ update_id: updateId, message: { text: `/new ${name}`, from: { id: 42 }, chat: { id: 42, type: 'private' }, ...extra } })
  }), context.app.env);
  context.redeem = (invite, deviceId = deviceA) => context.api('/api/invites/redeem', { invite, deviceId });
  context.register = (ticket, deviceId = deviceA) => context.api('/api/register', { registrationTicket: ticket, deviceId, authMethod: 'password', password });
  return context;
}

test('Windows config encodings and the CMD launcher remain compatible', () => {
  const text = 'TELEGRAM_BOT_TOKEN=123:test\r\nADMIN_TELEGRAM_ID=42\r\n';
  for (const bytes of [Buffer.from(text), Buffer.from('\uFEFF' + text), Buffer.from('\uFEFF' + text, 'utf16le')]) {
    assert.equal(parseConfig(bytes).ADMIN_TELEGRAM_ID, '42');
  }
  assert.throws(() => parseConfig(Buffer.from('ADMIN_TELEGRAM_ID=1\nADMIN_TELEGRAM_ID=2')));
  const cmd = readFileSync(new URL('../../START_ALMAS.cmd', import.meta.url));
  assert.ok(cmd.every(byte => byte < 128), 'CMD contains only ASCII');
  assert.ok(!/(?<!\r)\n/.test(cmd.toString()), 'CMD uses Windows CRLF');
  for (const path of ['index.html', 'stadium.html']) {
    const html = readFileSync(new URL('../../' + path, import.meta.url), 'utf8');
    for (const match of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) assert.doesNotThrow(() => new Function(match[1]));
  }
});

test('admin invite -> registration -> login -> validated stadium session, with repeat and password rejection', async t => {
  const f = await fixture(t);
  assert.equal((await f.telegram('Almas_01', 1, { from: { id: 99 } })).status, 200);
  assert.equal((await f.telegram('Almas_01', 2, { chat: { id: -100, type: 'group' } })).status, 200);
  assert.equal(f.documents.length, 0);
  assert.equal((await f.telegram('Almas_01', 3)).status, 200);
  assert.equal((await f.telegram('Almas_01', 3)).status, 200);
  assert.equal(f.documents.length, 1, 'Duplicate delivery must not create/send another invite');
  const invite = f.documents[0];
  assert.equal(invite.format, 'almasinvite');
  assert.ok(!JSON.stringify(invite).includes('Almas_01'), 'The invitation payload is encrypted');
  const redeemed = await f.redeem(invite);
  assert.equal(redeemed.status, 200);
  assert.equal((await f.redeem(invite, deviceB)).status, 409);
  assert.equal((await f.api('/api/register', { registrationTicket: redeemed.data.registrationTicket, deviceId: deviceA, authMethod: 'password', password: 'short' })).status, 400);
  const registered = await f.register(redeemed.data.registrationTicket);
  assert.equal(registered.status, 200);
  assert.equal((await f.redeem(invite)).status, 409);
  const body = { accountId: registered.data.player.id, deviceId: deviceA, deviceToken: registered.data.deviceToken, password };
  assert.equal((await f.api('/api/login/password', { ...body, deviceId: deviceB })).status, 401);
  assert.equal((await f.api('/api/login/password', body)).status, 200);
  for (let i = 0; i < 5; i++) {
    assert.equal((await f.api('/api/login/password', { ...body, password: 'WrongPass1!' })).status, i === 4 ? 429 : 401);
  }
  assert.equal((await f.api('/api/login/password', body)).status, 429);
  f.app.db.prepare('UPDATE users SET locked_until=0 WHERE id=?').bind(body.accountId).run();
  assert.equal((await f.api('/api/login/password', body)).status, 200);
  assert.equal((await f.api('/api/session', { accessToken: registered.data.accessToken })).status, 200);
  const concurrent = await Promise.all(Array.from({ length: 5 }, () => f.api('/api/login/password', { ...body, password: 'WrongPass1!' })));
  assert.ok(concurrent.some(result => result.status === 429));
  assert.equal((await f.api('/api/login/password', body)).status, 429, 'Concurrent attempts must also lock the account');
  const forged = 'e30.' + registered.data.accessToken.split('.')[1];
  assert.equal((await f.api('/api/session', { accessToken: forged })).status, 401);
  assert.equal((await f.api('/api/session', { accessToken: registered.data.accessToken }, 'https://untrusted.example')).status, 403);
  f.app.db.prepare("UPDATE users SET status='blocked' WHERE id=?").bind(body.accountId).run();
  assert.equal((await f.api('/api/session', { accessToken: registered.data.accessToken })).status, 401);
});

test('keys, pending invitations and account sessions survive a full server restart', async t => {
  const f = await fixture(t);
  await f.telegram('First_01', 10);
  const redeemed = await f.redeem(f.documents[0]);
  const registered = await f.register(redeemed.data.registrationTicket);
  await f.telegram('Second_02', 11);
  const pending = f.documents[1];
  const oldKeys = ['INVITE_ENCRYPTION_KEY', 'SESSION_SIGNING_KEY'].map(key => f.app.db.getState(key));
  await f.close(); await f.start();
  assert.deepEqual(['INVITE_ENCRYPTION_KEY', 'SESSION_SIGNING_KEY'].map(key => f.app.db.getState(key)), oldKeys);
  assert.equal((await f.api('/api/session', { accessToken: registered.data.accessToken })).status, 200);
  assert.equal((await f.api('/api/login/password', { accountId: registered.data.player.id, deviceToken: registered.data.deviceToken, deviceId: deviceA, password })).status, 200);
  assert.equal((await f.redeem(pending, deviceB)).status, 200);
});

test('two devices racing to redeem one invitation produce only one account', async t => {
  const f = await fixture(t);
  await f.telegram('Concurrent_01', 20);
  const results = await Promise.all([f.redeem(f.documents[0], deviceA), f.redeem(f.documents[0], deviceB)]);
  assert.deepEqual(results.map(r => r.status).sort(), [200, 409]);
  assert.equal(f.app.db.prepare('SELECT COUNT(*) AS count FROM users').first().count, 1);
});

test('Telegram delivery retry keeps the original invite and polling persists its offset', async t => {
  const f = await fixture(t);
  t.mock.method(console, 'error', () => {});
  f.failDocument = true;
  assert.equal((await f.telegram('Retry_01', 30)).status, 503);
  const original = f.app.db.prepare('SELECT document_json FROM telegram_invite_deliveries').first().document_json;
  f.failDocument = false;
  assert.equal((await f.telegram('Retry_01', 30)).status, 200);
  assert.deepEqual(f.documents[0], JSON.parse(original));
  assert.equal(f.app.db.prepare('SELECT COUNT(*) AS count FROM invites').first().count, 1);
  const controller = new AbortController(), offsets = [];
  await pollTelegram({ env: f.app.env, db: f.app.db, signal: controller.signal, log: () => {}, call: async (method, body) => {
    assert.equal(method, 'getUpdates'); offsets.push(body.offset);
    if (offsets.length === 1) return [{ update_id: 31 }, { update_id: 32 }];
    controller.abort(); return [];
  }});
  assert.deepEqual(offsets, [0, 33]);
  assert.equal(f.app.db.getState('telegram_offset:123456789'), '33');
});

test('public HTTP responses never serve server files and malformed requests return controlled errors', async t => {
  const f = await fixture(t);
  for (const path of ['/BOT_CONFIG_LOCAL.txt', '/server/config.mjs', '/auth-worker/src/worker.js', '/.git/config', '/almas.sqlite', '/telegram']) {
    assert.equal((await realFetch(f.origin + path)).status, 404, path);
  }
  const config = await (await realFetch(f.origin + '/app-config.js')).text();
  assert.match(config, /apiBase:window.location.origin/);
  assert.ok(!config.includes(testToken));
  const invalid = await realFetch(f.origin + '/api/register', { method: 'POST', headers: { Origin: f.origin }, body: '{broken' });
  assert.equal(invalid.status, 400);
  const blockedHost = await new Promise((resolve, reject) => {
    const request = httpRequest(f.origin + '/health', { headers: { Host: 'attacker.invalid' } }, response => { response.resume(); resolve(response.statusCode); });
    request.on('error', reject); request.end();
  });
  assert.equal(blockedHost, 403);
  const response = await worker.fetch(new Request('http://internal/telegram', { method: 'POST', body: '{}' }), { ...f.app.env, TELEGRAM_WEBHOOK_SECRET: '' });
  assert.equal(response.status, 403);
});

test('webhook migration preserves queued messages and transport errors cannot expose a bot token', async () => {
  const calls = [];
  const call = async (method, body) => { calls.push({ method, body }); return method === 'getMe' ? { username: 'test' } : { url: 'https://previous.example/telegram' }; };
  await assert.rejects(preparePolling(call, false), /take-over-webhook/);
  assert.ok(!calls.some(x => x.method === 'deleteWebhook'));
  await preparePolling(call, true);
  assert.deepEqual(calls.find(x => x.method === 'deleteWebhook').body, { drop_pending_updates: false });
  const failing = telegramClient(testToken, async url => { throw new Error(String(url)); });
  await assert.rejects(failing('getMe'), error => !error.message.includes(testToken) && error.message.includes('NETWORK'));
});
