import { DatabaseSync } from 'node:sqlite';
import { randomBytes } from 'node:crypto';
import { mkdirSync, readFileSync, chmodSync } from 'node:fs';
import { join } from 'node:path';

// The existing Worker can use this small, transactional D1-compatible adapter.
export function openDatabase(directory) {
  mkdirSync(directory, { recursive: true, mode: 0o700 });
  const filename = join(directory, 'almas.sqlite');
  const sqlite = new DatabaseSync(filename);
  try { chmodSync(filename, 0o600); } catch { /* Windows uses directory ACLs. */ }
  sqlite.exec('PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;');
  sqlite.exec(readFileSync(new URL('../auth-worker/schema.sql', import.meta.url), 'utf8'));
  sqlite.exec('CREATE TABLE IF NOT EXISTS server_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)');

  class Statement {
    constructor(sql, values = []) { this.statement = sqlite.prepare(sql); this.values = values; }
    bind(...values) { this.values = values; return this; }
    first() { return this.statement.get(...this.values) ?? null; }
    run() {
      const result = this.statement.run(...this.values);
      return { success: true, meta: { changes: Number(result.changes), last_row_id: Number(result.lastInsertRowid) } };
    }
  }

  const db = {
    prepare(sql) { return new Statement(sql); },
    batch(statements) {
      sqlite.exec('BEGIN IMMEDIATE');
      try {
        const results = statements.map(statement => statement.run());
        sqlite.exec('COMMIT');
        return results;
      } catch (error) { sqlite.exec('ROLLBACK'); throw error; }
    },
    getState(key) { return sqlite.prepare('SELECT value FROM server_state WHERE key = ?').get(key)?.value; },
    setState(key, value) {
      sqlite.prepare('INSERT INTO server_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value')
        .run(key, String(value));
    },
    close() { sqlite.close(); }
  };
  for (const key of ['INVITE_ENCRYPTION_KEY', 'SESSION_SIGNING_KEY', 'TELEGRAM_WEBHOOK_SECRET']) {
    sqlite.prepare('INSERT OR IGNORE INTO server_state(key,value) VALUES(?,?)')
      .run(key, randomBytes(32).toString('base64url'));
  }
  return db;
}
