CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS contacts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source TEXT NOT NULL,
  external_id TEXT NOT NULL,
  display_name TEXT,
  email TEXT,
  phone TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (source, external_id)
);

CREATE TABLE IF NOT EXISTS conversations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source TEXT NOT NULL,
  external_id TEXT NOT NULL,
  title TEXT,
  is_group BOOLEAN NOT NULL DEFAULT FALSE,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  first_message_at TIMESTAMPTZ,
  last_message_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (source, external_id)
);

CREATE TABLE IF NOT EXISTS messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source TEXT NOT NULL,
  external_id TEXT NOT NULL,
  conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  sender_contact_id UUID REFERENCES contacts(id) ON DELETE SET NULL,
  subject TEXT,
  body_text TEXT NOT NULL DEFAULT '',
  body_html TEXT,
  sent_at TIMESTAMPTZ NOT NULL,
  raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  search_vector TSVECTOR GENERATED ALWAYS AS (
    setweight(to_tsvector('english', COALESCE(subject, '')), 'A') ||
    setweight(to_tsvector('english', COALESCE(body_text, '')), 'B')
  ) STORED,
  UNIQUE (source, external_id)
);

CREATE TABLE IF NOT EXISTS attachments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  filename TEXT NOT NULL,
  content_type TEXT,
  storage_path TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS message_chunks (
  id BIGSERIAL PRIMARY KEY,
  message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  chunk_text TEXT NOT NULL,
  embedding_model TEXT,
  embedding VECTOR,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  search_vector TSVECTOR GENERATED ALWAYS AS (
    to_tsvector('english', COALESCE(chunk_text, ''))
  ) STORED,
  UNIQUE (message_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS sync_state (
  key TEXT PRIMARY KEY,
  state JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_contacts_source_external_id
  ON contacts(source, external_id);

CREATE INDEX IF NOT EXISTS idx_conversations_source_external_id
  ON conversations(source, external_id);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_id_sent_at
  ON messages(conversation_id, sent_at DESC);

CREATE INDEX IF NOT EXISTS idx_messages_source_sent_at
  ON messages(source, sent_at DESC);

CREATE INDEX IF NOT EXISTS idx_messages_search_vector
  ON messages USING GIN (search_vector);

CREATE INDEX IF NOT EXISTS idx_message_chunks_message_id
  ON message_chunks(message_id, chunk_index);

CREATE INDEX IF NOT EXISTS idx_message_chunks_search_vector
  ON message_chunks USING GIN (search_vector);

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_contacts_updated_at ON contacts;
CREATE TRIGGER trg_contacts_updated_at
BEFORE UPDATE ON contacts
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_conversations_updated_at ON conversations;
CREATE TRIGGER trg_conversations_updated_at
BEFORE UPDATE ON conversations
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_messages_updated_at ON messages;
CREATE TRIGGER trg_messages_updated_at
BEFORE UPDATE ON messages
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE FUNCTION search_messages_lexical(
  search_query TEXT,
  limit_count INTEGER DEFAULT 10,
  filter_source TEXT DEFAULT NULL
)
RETURNS TABLE (
  message_id UUID,
  source TEXT,
  external_id TEXT,
  conversation_id UUID,
  sent_at TIMESTAMPTZ,
  subject TEXT,
  body_text TEXT,
  rank REAL
) AS $$
  SELECT
    m.id AS message_id,
    m.source,
    m.external_id,
    m.conversation_id,
    m.sent_at,
    m.subject,
    m.body_text,
    ts_rank_cd(m.search_vector, websearch_to_tsquery('english', search_query)) AS rank
  FROM messages m
  WHERE m.search_vector @@ websearch_to_tsquery('english', search_query)
    AND (filter_source IS NULL OR m.source = filter_source)
  ORDER BY rank DESC, m.sent_at DESC
  LIMIT limit_count;
$$ LANGUAGE SQL STABLE;

CREATE OR REPLACE FUNCTION search_message_chunks_semantic(
  query_embedding VECTOR,
  limit_count INTEGER DEFAULT 10,
  filter_source TEXT DEFAULT NULL
)
RETURNS TABLE (
  message_id UUID,
  chunk_index INTEGER,
  source TEXT,
  external_id TEXT,
  conversation_id UUID,
  sent_at TIMESTAMPTZ,
  chunk_text TEXT,
  embedding_model TEXT,
  distance DOUBLE PRECISION
) AS $$
  SELECT
    m.id AS message_id,
    mc.chunk_index,
    m.source,
    m.external_id,
    m.conversation_id,
    m.sent_at,
    mc.chunk_text,
    mc.embedding_model,
    mc.embedding <=> query_embedding AS distance
  FROM message_chunks mc
  JOIN messages m ON m.id = mc.message_id
  WHERE mc.embedding IS NOT NULL
    AND (filter_source IS NULL OR m.source = filter_source)
  ORDER BY mc.embedding <=> query_embedding ASC, m.sent_at DESC
  LIMIT limit_count;
$$ LANGUAGE SQL STABLE;
