PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS invites (
  id TEXT PRIMARY KEY,
  token_hash TEXT NOT NULL,
  player_name TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  used_at INTEGER,
  used_device_hash TEXT,
  created_by_telegram_id TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_invites_available
ON invites(expires_at)
WHERE used_at IS NULL;

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  player_name TEXT NOT NULL UNIQUE,
  invite_id TEXT NOT NULL UNIQUE REFERENCES invites(id),
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'active', 'blocked')),
  auth_method TEXT
    CHECK (auth_method IS NULL OR auth_method IN ('password', 'device')),
  password_salt TEXT,
  password_hash TEXT,
  password_iterations INTEGER,
  device_hash TEXT NOT NULL,
  device_token_hash TEXT,
  failed_attempts INTEGER NOT NULL DEFAULT 0,
  locked_until INTEGER,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_device_hash
ON users(device_hash);

CREATE TABLE IF NOT EXISTS registration_tickets (
  token_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  expires_at INTEGER NOT NULL,
  consumed_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_registration_tickets_expiry
ON registration_tickets(expires_at);

PRAGMA optimize;

