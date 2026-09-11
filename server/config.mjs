import { existsSync, readFileSync } from 'node:fs';
import { homedir, networkInterfaces } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');

export function parseConfig(bytes) {
  const utf16 = bytes[0] === 0xff && bytes[1] === 0xfe;
  const text = bytes.toString(utf16 ? 'utf16le' : 'utf8').replace(/^\uFEFF/, '');
  const settings = {};
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim() || line.trim().startsWith('#')) continue;
    const match = line.match(/^\s*([A-Z][A-Z0-9_]*)\s*=(.*)$/);
    if (!match) throw new Error('Config format must be KEY=value, one setting per line.');
    if (Object.hasOwn(settings, match[1])) throw new Error('A setting is repeated in the config file.');
    let value = match[2].trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) value = value.slice(1, -1);
    settings[match[1]] = value;
  }
  return settings;
}

function origin(value) {
  const url = new URL(value);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('The server URL must be an HTTP(S) origin without a path, password or query.');
  }
  return url.origin;
}

export function loadConfig(args = process.argv.slice(2), environment = process.env) {
  const configIndex = args.indexOf('--config');
  if (configIndex >= 0 && !args[configIndex + 1]) throw new Error('--config needs a file path.');
  const explicit = configIndex >= 0 ? args[configIndex + 1] : environment.ALMAS_CONFIG_PATH;
  const candidates = explicit ? [resolve(explicit)] : [
    join(projectRoot, 'BOT_CONFIG_LOCAL.txt'),
    join(projectRoot, 'auth-worker', 'BOT_CONFIG_LOCAL.txt'),
    join(homedir(), 'Downloads', 'BOT_CONFIG_LOCAL.txt')
  ];
  const configPath = candidates.find(path => existsSync(path));
  if (explicit && !configPath) throw new Error('The selected config file was not found.');
  const settings = configPath ? parseConfig(readFileSync(configPath)) : {};
  const value = name => environment[name] || settings[name] || '';
  const noBot = args.includes('--no-bot');
  const token = value('TELEGRAM_BOT_TOKEN');
  const adminId = value('ADMIN_TELEGRAM_ID');
  if (!noBot && !/^\d+:[A-Za-z0-9_-]{20,}$/.test(token)) {
    throw new Error('Put your existing BOT_CONFIG_LOCAL.txt in Downloads or beside START_ALMAS.cmd. TELEGRAM_BOT_TOKEN is missing or invalid.');
  }
  if (!noBot && !/^[1-9]\d*$/.test(adminId)) throw new Error('ADMIN_TELEGRAM_ID is missing or invalid in BOT_CONFIG_LOCAL.txt.');
  const port = Number(value('PORT') || '8080');
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('PORT must be between 1 and 65535.');
  const publicUrl = value('ALMAS_PUBLIC_URL') ? origin(value('ALMAS_PUBLIC_URL')) : '';
  if (publicUrl && !publicUrl.startsWith('https://')) throw new Error('ALMAS_PUBLIC_URL must use HTTPS.');
  const dataRoot = process.platform === 'win32'
    ? join(environment.LOCALAPPDATA || homedir(), 'AlmasProjekt', 'server')
    : join(environment.XDG_DATA_HOME || join(homedir(), '.local', 'share'), 'almas-projekt');
  const localAddresses = Object.values(networkInterfaces()).flat().filter(item => item && item.family === 'IPv4' && !item.internal)
    .map(item => item.address).filter(ip => /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(ip));
  const origins = new Set([`http://localhost:${port}`, `http://127.0.0.1:${port}`, ...localAddresses.map(ip => `http://${ip}:${port}`)]);
  if (publicUrl) origins.add(publicUrl);
  if (value('ALMAS_APP_ORIGIN')) origins.add(origin(value('ALMAS_APP_ORIGIN')));
  return {
    token, adminId, port, noBot, publicUrl, localAddresses, origins,
    host: value('HOST') || '0.0.0.0',
    dataDirectory: resolve(value('ALMAS_DATA_DIR') || dataRoot),
    takeOverWebhook: args.includes('--take-over-webhook'),
    openBrowser: args.includes('--open')
  };
}
