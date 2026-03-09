ALTER TABLE messages
  ADD COLUMN IF NOT EXISTS reply_to TEXT,
  ADD COLUMN IF NOT EXISTS message_id_header TEXT,
  ADD COLUMN IF NOT EXISTS in_reply_to TEXT,
  ADD COLUMN IF NOT EXISTS references_header TEXT,
  ADD COLUMN IF NOT EXISTS list_id TEXT,
  ADD COLUMN IF NOT EXISTS delivered_to TEXT;

CREATE INDEX IF NOT EXISTS idx_messages_message_id_header
  ON messages(message_id_header);

CREATE INDEX IF NOT EXISTS idx_messages_in_reply_to
  ON messages(in_reply_to);

CREATE INDEX IF NOT EXISTS idx_messages_list_id
  ON messages(list_id);

CREATE TABLE IF NOT EXISTS message_participants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  contact_id UUID REFERENCES contacts(id) ON DELETE SET NULL,
  participant_type TEXT NOT NULL CHECK (participant_type IN ('from', 'reply_to', 'to', 'cc', 'bcc')),
  position INTEGER NOT NULL DEFAULT 0,
  header_value TEXT,
  display_name TEXT,
  email TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (message_id, participant_type, position)
);

CREATE INDEX IF NOT EXISTS idx_message_participants_message
  ON message_participants(message_id, participant_type, position);

CREATE INDEX IF NOT EXISTS idx_message_participants_email
  ON message_participants(email);

CREATE INDEX IF NOT EXISTS idx_message_participants_contact
  ON message_participants(contact_id);
