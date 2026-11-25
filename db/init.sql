-- Schema nach technische-umsetzung.md Abschnitt 4. Wird beim ersten Start von Postgres ausgeführt.
-- Frisch aufsetzen: docker compose down -v && docker compose up -d
CREATE EXTENSION IF NOT EXISTS vector;

-- Workspace und Kanäle
CREATE TABLE workspaces (
  id   text PRIMARY KEY,
  name text NOT NULL
);
-- "doc:…", "table:…", "run:…", "user:…", "workspace:…"
CREATE TABLE channels (
  id  text PRIMARY KEY,
  seq bigint NOT NULL DEFAULT 0
);

-- Nutzer, Rollen, Agenten (5.8)
CREATE TABLE users (
  id            text PRIMARY KEY,
  external_id   text UNIQUE,
  name          text NOT NULL,
  email         text UNIQUE,
  password_hash text,                       -- Demo-Login (1.1); bei OIDC leer
  active        boolean NOT NULL DEFAULT true
);
CREATE TABLE agents (
  id           text PRIMARY KEY,
  workspace_id text NOT NULL REFERENCES workspaces,
  name         text NOT NULL,
  client_id    text UNIQUE,
  active       boolean NOT NULL DEFAULT true
);
CREATE TABLE roles (
  id           text PRIMARY KEY,
  workspace_id text NOT NULL REFERENCES workspaces,
  key          text NOT NULL,
  name         text NOT NULL,
  UNIQUE (workspace_id, key)
);
CREATE TABLE member_roles (
  workspace_id text NOT NULL,
  member_id    text NOT NULL,               -- usr_… oder agt_…
  role_id      text NOT NULL REFERENCES roles ON DELETE RESTRICT,
  PRIMARY KEY (member_id, role_id)
);

-- Tabellen (2)
CREATE TABLE tables (
  id             text PRIMARY KEY,
  workspace_id   text NOT NULL REFERENCES workspaces,
  key            text NOT NULL,
  name           text NOT NULL,
  display_column text,
  version        int NOT NULL DEFAULT 1,
  UNIQUE (workspace_id, key)
);
CREATE TABLE columns (
  id         text PRIMARY KEY,
  table_id   text NOT NULL REFERENCES tables ON DELETE CASCADE,
  key        text NOT NULL,
  name       text NOT NULL,
  type       jsonb NOT NULL,
  required   boolean NOT NULL DEFAULT false,
  "unique"   boolean NOT NULL DEFAULT false,
  "default"  jsonb,
  position   text COLLATE "C" NOT NULL,
  UNIQUE (table_id, key)
);
CREATE TABLE rows (
  id         text PRIMARY KEY,
  table_id   text NOT NULL REFERENCES tables ON DELETE CASCADE,
  position   text COLLATE "C" NOT NULL,
  "values"   jsonb NOT NULL DEFAULT '{}',   -- { col_id: value }
  version    int NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  created_by jsonb,
  updated_at timestamptz NOT NULL DEFAULT now(),
  updated_by jsonb
);
-- Referenzspalten, für on_delete und Rückwärtssuche
CREATE TABLE row_links (
  from_row  text NOT NULL REFERENCES rows ON DELETE CASCADE,
  column_id text NOT NULL,
  to_row    text NOT NULL REFERENCES rows,
  PRIMARY KEY (from_row, column_id, to_row)
);

-- Dokumente (3)
CREATE TABLE documents (
  id             text PRIMARY KEY,
  workspace_id   text NOT NULL REFERENCES workspaces,
  title          text NOT NULL,
  owner_workflow text,
  owner_step     text,
  version        int NOT NULL DEFAULT 1,
  updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE blocks (
  id        text PRIMARY KEY,
  doc_id    text NOT NULL REFERENCES documents ON DELETE CASCADE,
  parent_id text,
  position  text COLLATE "C" NOT NULL,
  type      text NOT NULL,
  props     jsonb NOT NULL DEFAULT '{}',
  version   int NOT NULL DEFAULT 1
);

-- Formulare (4)
CREATE TABLE form_drafts (
  form_block text NOT NULL,
  scope      text NOT NULL,                 -- "run:run_42" oder "user:usr_1"
  "values"   jsonb NOT NULL DEFAULT '{}',
  version    int NOT NULL DEFAULT 1,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (form_block, scope)
);
CREATE TABLE form_submissions (
  id         text PRIMARY KEY,              -- = submission_id vom Client
  form_block text NOT NULL,
  run_id     text,
  button     text NOT NULL,
  "values"   jsonb NOT NULL DEFAULT '{}',
  results    jsonb NOT NULL DEFAULT '{}',
  actor      jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Workflows (5)
CREATE TABLE workflows (
  id             text PRIMARY KEY,
  workspace_id   text NOT NULL REFERENCES workspaces,
  key            text NOT NULL,
  name           text NOT NULL,
  draft          jsonb NOT NULL,
  latest_version int,
  UNIQUE (workspace_id, key)
);
CREATE TABLE workflow_versions (
  workflow_id  text NOT NULL REFERENCES workflows ON DELETE CASCADE,
  version      int NOT NULL,
  definition   jsonb NOT NULL,
  documents    jsonb NOT NULL,              -- eingefrorene Blöcke je Dokument
  published_at timestamptz NOT NULL DEFAULT now(),
  published_by jsonb,
  PRIMARY KEY (workflow_id, version)
);
CREATE TABLE runs (
  id              text PRIMARY KEY,
  workflow_id     text NOT NULL REFERENCES workflows,
  version         int NOT NULL,
  title           text NOT NULL,
  status          text NOT NULL CHECK (status IN ('active','completed','cancelled')),
  current_step    text,
  result          jsonb,
  parent_run      text,
  parent_step     text,
  parent_block    text,
  input           jsonb NOT NULL DEFAULT '{}',
  steps           jsonb NOT NULL DEFAULT '{}',
  started_by      jsonb NOT NULL,
  started_by_id   text NOT NULL,            -- für "Meine Anträge"
  started_at      timestamptz NOT NULL DEFAULT now(),
  ended_at        timestamptz,
  updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE tasks (
  id               text PRIMARY KEY,
  run_id           text NOT NULL REFERENCES runs,
  step             text NOT NULL,
  status           text NOT NULL CHECK (status IN ('open','done','cancelled')),
  candidate_users  text[] NOT NULL DEFAULT '{}',
  candidate_roles  text[] NOT NULL DEFAULT '{}',
  excluded         text[] NOT NULL DEFAULT '{}',
  claimed_by       jsonb,
  claimed_by_id    text,
  created_at       timestamptz NOT NULL DEFAULT now(),
  due_at           timestamptz,
  completed_by     jsonb,
  completed_at     timestamptz,
  outcome          text
);
CREATE TABLE run_events (
  id      text PRIMARY KEY,
  run_id  text NOT NULL REFERENCES runs,
  at      timestamptz NOT NULL DEFAULT now(),
  actor   jsonb,
  type    text NOT NULL,
  step    text,
  outcome text,
  label   text,
  text    text
);
CREATE TABLE notifications (
  id           text PRIMARY KEY,
  recipient_id text NOT NULL,
  run_id       text,
  task_id      text,
  type         text NOT NULL,
  payload      jsonb NOT NULL DEFAULT '{}',
  created_at   timestamptz NOT NULL DEFAULT now(),
  read_at      timestamptz
);

-- Querschnitt
CREATE TABLE oplog (
  channel    text NOT NULL,
  seq        bigint NOT NULL,
  batch_id   text NOT NULL,
  actor      jsonb,
  ops        jsonb NOT NULL,
  inverse    jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (channel, seq)
);
-- Idempotenz, nach 24 h aufräumen
CREATE TABLE batches (
  batch_id   text PRIMARY KEY,
  result     jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
-- vorbereitete Imports, nach 1 h bzw. nach Verbrauch aufräumen
CREATE TABLE imports (
  id           text PRIMARY KEY,
  workspace_id text NOT NULL,
  actor        jsonb,
  source       text NOT NULL CHECK (source IN ('xlsx','docx')),
  ops          jsonb NOT NULL,
  created      jsonb NOT NULL,
  warnings     jsonb NOT NULL DEFAULT '[]',
  used_at      timestamptz,
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE "references" (
  source_kind text NOT NULL,
  source_id   text NOT NULL,
  target_kind text NOT NULL,
  target_id   text NOT NULL,
  via         text NOT NULL
);
-- Dimension 384 passt zu kleinen Embedding-Modellen (config.py: embedding_dim)
CREATE TABLE embeddings (
  id           bigserial PRIMARY KEY,
  workspace_id text NOT NULL,
  source_kind  text NOT NULL,
  source_id    text NOT NULL,
  block_ids    text[] NOT NULL DEFAULT '{}',
  chunk_hash   text NOT NULL,
  content      text NOT NULL,
  tsv          tsvector GENERATED ALWAYS AS (to_tsvector('german', content)) STORED,
  embedding    vector(384),
  model        text NOT NULL,
  updated_at   timestamptz NOT NULL DEFAULT now()
);

-- Indizes
CREATE INDEX ON blocks (doc_id, parent_id, position);
CREATE INDEX ON rows (table_id, position);
CREATE INDEX ON rows USING gin ("values" jsonb_path_ops);
CREATE INDEX ON row_links (to_row);
CREATE INDEX ON "references" (target_kind, target_id);
CREATE INDEX ON runs (workflow_id, status);
CREATE INDEX ON runs (started_by_id, status);
CREATE INDEX ON tasks (status) WHERE status = 'open';
CREATE INDEX ON tasks USING gin (candidate_users) WHERE status = 'open';
CREATE INDEX ON tasks USING gin (candidate_roles) WHERE status = 'open';
CREATE INDEX ON run_events (run_id, at);
CREATE INDEX ON notifications (recipient_id, created_at) WHERE read_at IS NULL;
CREATE INDEX ON embeddings USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON embeddings USING gin (tsv);

-- Standard-Workspace für die Demo (Seed 5.5 ergänzt Nutzer und Rollen)
INSERT INTO workspaces (id, name) VALUES ('ws_demo', 'Demo');
