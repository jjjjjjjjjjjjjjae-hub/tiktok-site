import worker from '../auth-worker/src/worker.js';
import { setTimeout as delay } from 'node:timers/promises';

export class TelegramError extends Error {
  constructor(method, code) { super(`Telegram ${method} failed (${code}).`); this.code = code; }
}

export function telegramClient(token, transport = fetch) {
  return async (method, body = {}, signal) => {
    let response;
    try {
      response = await transport(`https://api.telegram.org/bot${token}/${method}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body), signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(45000)]) : AbortSignal.timeout(45000)
      });
    } catch {
      if (signal?.aborted) throw new TelegramError(method, 'STOPPED');
      throw new TelegramError(method, 'NETWORK');
    }
    let result;
    try { result = await response.json(); } catch { throw new TelegramError(method, response.status); }
    if (!response.ok || !result.ok) throw new TelegramError(method, result.error_code || response.status);
    return result.result;
  };
}

export async function preparePolling(call, takeOverWebhook, signal) {
  const identity = await call('getMe', {}, signal);
  const info = await call('getWebhookInfo', {}, signal);
  if (info.url) {
    if (!takeOverWebhook) {
      throw new Error('This bot already has a webhook. To move it to this server, run START_ALMAS.cmd --take-over-webhook. Pending messages will be kept.');
    }
    await call('deleteWebhook', { drop_pending_updates: false }, signal);
  }
  return identity;
}

export async function pollTelegram({ call, env, db, signal, log = console.log, onState = () => {} }) {
  const offsetKey = 'telegram_offset:' + String(env.TELEGRAM_BOT_TOKEN).split(':')[0];
  let offset = Number(db.getState(offsetKey) || 0);
  while (!signal.aborted) {
    try {
      const updates = await call('getUpdates', { offset, timeout: 30, allowed_updates: ['message'], limit: 20 }, signal);
      onState('connected');
      for (const update of updates) {
        if (signal.aborted) break;
        if (!Number.isSafeInteger(update.update_id) || update.update_id < offset) continue;
        const response = await worker.fetch(new Request('http://almas.internal/telegram', {
          method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Telegram-Bot-Api-Secret-Token': env.TELEGRAM_WEBHOOK_SECRET },
          body: JSON.stringify(update)
        }), env);
        if (!response.ok) throw new TelegramError('processUpdate', response.status);
        offset = update.update_id + 1;
        db.setState(offsetKey, offset);
      }
    } catch (error) {
      if (signal.aborted) break;
      if (error.code === 401 || error.code === 409) {
        onState('stopped');
        log(error.code === 409 ? 'Bot stopped: another process or webhook is using this bot. Close the other copy and restart.' : 'Bot stopped: check the token in your local config.');
        return;
      }
      onState('reconnecting');
      log('Telegram is unavailable. Retrying in 5 seconds.');
      await delay(5000, undefined, { signal }).catch(() => {});
    }
  }
}
