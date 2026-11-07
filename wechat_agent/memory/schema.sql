-- ============================================================================
-- DSH-WeChat-Agent V1.0 双库 DDL（里程碑 M0-06）
--
-- 本文件按 `-- [DB: <kind>]` 分段；由 memory/db.py 解析后分别应用到：
--   [DB: chat_history] -> data/chat_history.db（流水库，高频写）
--   [DB: memory]       -> data/memory.db      （核心档案库，低频写、重读）
--
-- 纪律：
--   * 所有语句必须幂等（IF NOT EXISTS），迁移与「自愈修复」共用同一份 SQL；
--   * 外键仅在 chat_history 内生效；两个库物理分离，禁止跨库 JOIN；
--   * FTS5 使用 external content 表 + 触发器同步，避免冗余存储。
-- ============================================================================

-- ============================================================================
-- [DB: chat_history]
-- ============================================================================
CREATE TABLE IF NOT EXISTS schema_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chats (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL UNIQUE,                       -- 会话显示名
  type          TEXT NOT NULL DEFAULT 'private' CHECK (type IN ('private', 'group')),
  enabled       INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  alias         TEXT,                                       -- 控制台短名
  auto_reply    INTEGER NOT NULL DEFAULT 1 CHECK (auto_reply IN (0, 1)),
  last_msg_hash TEXT,                                       -- 便捷锚点（最新一条）
  note          TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS messages (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id      INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
  direction    TEXT NOT NULL CHECK (direction IN ('in', 'out', 'self', 'system')),
  sender_name  TEXT,                                        -- 群聊成员名；私聊可空
  role         TEXT,                                        -- LLM role: user / assistant / system
  content      TEXT NOT NULL,
  norm_text    TEXT NOT NULL,                               -- 规范化文本（去空白/全角统一）
  content_hash TEXT NOT NULL,                               -- sha1(norm_text)[:16]
  msg_ts       TEXT,                                        -- 微信复制出的时间戳（可空）
  source       TEXT NOT NULL,                               -- rpa_capture | self_writeback | console_override | plugin
  status       TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'recalled', 'pending_confirm', 'failed')),
  dedup_count  INTEGER NOT NULL DEFAULT 0,                   -- 同 hash 在同会话内的累计出现次数
  raw_meta     TEXT,                                        -- JSON：抓屏序号/置信度/解析策略
  created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_msg_chat_hash ON messages(chat_id, content_hash);
CREATE INDEX IF NOT EXISTS idx_msg_chat_id   ON messages(chat_id, id DESC);

-- FTS5：external content 表（chat_history 内的全文检索）
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
  norm_text,
  content='messages',
  content_rowid='id',
  tokenize='unicode61'
);
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
  INSERT INTO messages_fts(rowid, norm_text) VALUES (new.id, new.norm_text);
END;
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
  INSERT INTO messages_fts(messages_fts, rowid, norm_text) VALUES ('delete', old.id, old.norm_text);
END;
CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
  INSERT INTO messages_fts(messages_fts, rowid, norm_text) VALUES ('delete', old.id, old.norm_text);
  INSERT INTO messages_fts(rowid, norm_text) VALUES (new.id, new.norm_text);
END;

-- 长期记忆提炼游标（M3）
CREATE TABLE IF NOT EXISTS extract_cursor (
  chat_id     INTEGER PRIMARY KEY,
  upto_msg_id INTEGER NOT NULL DEFAULT 0,
  updated_at  TEXT
);

-- 审计：每次真实发送 / 接管 / 失败留证（M6）
CREATE TABLE IF NOT EXISTS audit_log (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id    INTEGER,
  direction  TEXT,
  trigger    TEXT,                                          -- auto | override | plugin | retry
  content    TEXT,
  payload    TEXT,
  result     TEXT,                                          -- sent | verify_failed | skipped | error
  trace_id   TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_audit_chat_created ON audit_log(chat_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_trace ON audit_log(trace_id);

-- 定时任务 / 插件任务（M6，发圈等）
CREATE TABLE IF NOT EXISTS tasks (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  type       TEXT NOT NULL,
  payload    TEXT NOT NULL,                                 -- JSON
  state      TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'running', 'done', 'failed', 'cancelled')),
  run_at     TEXT,
  attempts   INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_tasks_state_run ON tasks(state, run_at);

-- 运行态持久化（M4 崩溃恢复：PAUSED/IDLE、最近 trace、各类游标）
CREATE TABLE IF NOT EXISTS runtime_state (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);


CREATE TABLE IF NOT EXISTS pending_replies (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id     INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
  message_id  INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  content     TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done')),
  created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
  UNIQUE(chat_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_pending_chat ON pending_replies(chat_id, status, id);

-- ============================================================================
-- [DB: memory]
-- ============================================================================
CREATE TABLE IF NOT EXISTS schema_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id        INTEGER,                                    -- NULL = 跨会话全局（用户画像/偏好）
  category       TEXT NOT NULL CHECK (category IN ('profile', 'preference', 'event', 'relation', 'rule', 'summary')),
  mem_key        TEXT,                                       -- 可合并键，如 "生日"、"工作"
  content        TEXT NOT NULL,
  confidence     REAL NOT NULL DEFAULT 0.7 CHECK (confidence >= 0.0 AND confidence <= 1.0),
  importance     REAL NOT NULL DEFAULT 0.5 CHECK (importance >= 0.0 AND importance <= 1.0),
  source_msg_ids TEXT,                                       -- JSON 数组
  embedding      BLOB,                                       -- 预留（V1 不写，V1.1+ 可接向量）
  ttl_days       INTEGER,                                    -- event 类可过期
  created_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
  updated_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
  deleted        INTEGER NOT NULL DEFAULT 0 CHECK (deleted IN (0, 1))  -- 软删（支持"忘记这件事"）
);
CREATE INDEX IF NOT EXISTS idx_mem_chat_cat ON memories(chat_id, category, deleted);
CREATE UNIQUE INDEX IF NOT EXISTS uq_mem_upsert ON memories(chat_id, category, mem_key);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
  content,
  mem_key,
  content='memories',
  content_rowid='id',
  tokenize='unicode61'
);
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
  INSERT INTO memories_fts(rowid, content, mem_key) VALUES (new.id, new.content, new.mem_key);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
  INSERT INTO memories_fts(memories_fts, rowid, content, mem_key) VALUES ('delete', old.id, old.content, old.mem_key);
END;
CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
  INSERT INTO memories_fts(memories_fts, rowid, content, mem_key) VALUES ('delete', old.id, old.content, old.mem_key);
  INSERT INTO memories_fts(rowid, content, mem_key) VALUES (new.id, new.content, new.mem_key);
END;

-- 会话级滚动摘要（M5）
CREATE TABLE IF NOT EXISTS conversation_summary (
  chat_id     INTEGER PRIMARY KEY,
  summary     TEXT NOT NULL,
  upto_msg_id INTEGER NOT NULL,
  updated_at  TEXT
);
