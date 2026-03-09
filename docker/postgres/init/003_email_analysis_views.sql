CREATE INDEX IF NOT EXISTS idx_contacts_lower_email
  ON contacts(LOWER(email));

CREATE INDEX IF NOT EXISTS idx_message_participants_lower_email
  ON message_participants(LOWER(email));


CREATE OR REPLACE VIEW message_analysis AS
SELECT
  m.id AS message_id,
  m.source,
  m.external_id,
  m.conversation_id,
  m.sent_at,
  m.subject,
  COALESCE(sender.display_name, from_participant.display_name) AS sender_name,
  COALESCE(sender.email, from_participant.email) AS sender_email,
  m.reply_to,
  m.message_id_header,
  m.in_reply_to,
  m.references_header,
  m.list_id,
  m.delivered_to,
  COALESCE(participant_stats.to_count, 0) AS to_count,
  COALESCE(participant_stats.cc_count, 0) AS cc_count,
  COALESCE(participant_stats.bcc_count, 0) AS bcc_count,
  COALESCE(participant_stats.reply_to_count, 0) AS reply_to_count,
  COALESCE(participant_stats.participant_count, 0) AS participant_count,
  COALESCE(participant_stats.to_emails, ARRAY[]::TEXT[]) AS to_emails,
  COALESCE(participant_stats.cc_emails, ARRAY[]::TEXT[]) AS cc_emails,
  COALESCE(participant_stats.bcc_emails, ARRAY[]::TEXT[]) AS bcc_emails,
  COALESCE(participant_stats.reply_to_emails, ARRAY[]::TEXT[]) AS reply_to_emails,
  COALESCE(participant_stats.participant_emails, ARRAY[]::TEXT[]) AS participant_emails
FROM messages m
LEFT JOIN contacts sender ON sender.id = m.sender_contact_id
LEFT JOIN LATERAL (
  SELECT
    mp.display_name,
    mp.email
  FROM message_participants mp
  WHERE mp.message_id = m.id
    AND mp.participant_type = 'from'
  ORDER BY mp.position ASC
  LIMIT 1
) AS from_participant ON TRUE
LEFT JOIN LATERAL (
  SELECT
    COUNT(*) FILTER (WHERE mp.participant_type = 'to') AS to_count,
    COUNT(*) FILTER (WHERE mp.participant_type = 'cc') AS cc_count,
    COUNT(*) FILTER (WHERE mp.participant_type = 'bcc') AS bcc_count,
    COUNT(*) FILTER (WHERE mp.participant_type = 'reply_to') AS reply_to_count,
    COUNT(*) AS participant_count,
    ARRAY_REMOVE(ARRAY_AGG(DISTINCT mp.email) FILTER (WHERE mp.participant_type = 'to'), NULL) AS to_emails,
    ARRAY_REMOVE(ARRAY_AGG(DISTINCT mp.email) FILTER (WHERE mp.participant_type = 'cc'), NULL) AS cc_emails,
    ARRAY_REMOVE(ARRAY_AGG(DISTINCT mp.email) FILTER (WHERE mp.participant_type = 'bcc'), NULL) AS bcc_emails,
    ARRAY_REMOVE(ARRAY_AGG(DISTINCT mp.email) FILTER (WHERE mp.participant_type = 'reply_to'), NULL) AS reply_to_emails,
    ARRAY_REMOVE(ARRAY_AGG(DISTINCT mp.email), NULL) AS participant_emails
  FROM message_participants mp
  WHERE mp.message_id = m.id
) AS participant_stats ON TRUE;


CREATE OR REPLACE VIEW conversation_analysis AS
SELECT
  c.id AS conversation_id,
  c.source,
  c.external_id,
  c.title,
  c.is_group,
  c.first_message_at,
  c.last_message_at,
  COUNT(DISTINCT m.id) AS message_count,
  COUNT(DISTINCT COALESCE(mp.email, sender.email)) FILTER (WHERE COALESCE(mp.email, sender.email) IS NOT NULL) AS unique_email_count,
  COUNT(DISTINCT sender.email) FILTER (WHERE sender.email IS NOT NULL) AS unique_sender_count,
  COUNT(DISTINCT mp.email) FILTER (WHERE mp.participant_type IN ('to', 'cc', 'bcc') AND mp.email IS NOT NULL) AS unique_recipient_count,
  ARRAY_REMOVE(ARRAY_AGG(DISTINCT sender.email), NULL) AS sender_emails,
  ARRAY_REMOVE(ARRAY_AGG(DISTINCT mp.email) FILTER (WHERE mp.participant_type IN ('to', 'cc', 'bcc')), NULL) AS recipient_emails,
  ARRAY_REMOVE(ARRAY_AGG(DISTINCT mp.email), NULL) AS participant_emails
FROM conversations c
LEFT JOIN messages m ON m.conversation_id = c.id
LEFT JOIN contacts sender ON sender.id = m.sender_contact_id
LEFT JOIN message_participants mp ON mp.message_id = m.id
GROUP BY
  c.id,
  c.source,
  c.external_id,
  c.title,
  c.is_group,
  c.first_message_at,
  c.last_message_at;


CREATE OR REPLACE VIEW contact_activity AS
WITH participant_rows AS (
  SELECT
    LOWER(COALESCE(mp.email, c.email)) AS email,
    COALESCE(NULLIF(mp.display_name, ''), NULLIF(c.display_name, ''), COALESCE(mp.email, c.email)) AS display_name,
    mp.participant_type,
    mp.message_id,
    m.conversation_id,
    m.sent_at
  FROM message_participants mp
  JOIN messages m ON m.id = mp.message_id
  LEFT JOIN contacts c ON c.id = mp.contact_id
  WHERE COALESCE(mp.email, c.email) IS NOT NULL
)
SELECT
  email,
  (ARRAY_AGG(display_name ORDER BY sent_at DESC) FILTER (WHERE display_name IS NOT NULL))[1] AS display_name,
  COUNT(*) FILTER (WHERE participant_type = 'from') AS sent_count,
  COUNT(*) FILTER (WHERE participant_type = 'reply_to') AS reply_to_count,
  COUNT(*) FILTER (WHERE participant_type = 'to') AS to_count,
  COUNT(*) FILTER (WHERE participant_type = 'cc') AS cc_count,
  COUNT(*) FILTER (WHERE participant_type = 'bcc') AS bcc_count,
  COUNT(DISTINCT message_id) AS message_count,
  COUNT(DISTINCT conversation_id) AS conversation_count,
  MIN(sent_at) AS first_seen_at,
  MAX(sent_at) AS last_seen_at
FROM participant_rows
GROUP BY email;


CREATE OR REPLACE FUNCTION messages_with_contact(
  contact_email TEXT,
  limit_count INTEGER DEFAULT 100
)
RETURNS TABLE (
  message_id UUID,
  conversation_id UUID,
  sent_at TIMESTAMPTZ,
  subject TEXT,
  direction TEXT,
  sender_email TEXT,
  matched_roles TEXT[],
  participant_emails TEXT[]
) AS $$
  SELECT
    m.id AS message_id,
    m.conversation_id,
    m.sent_at,
    m.subject,
    CASE
      WHEN LOWER(COALESCE(sender.email, from_participant.email, '')) = LOWER(contact_email) THEN 'sent'
      ELSE 'received'
    END AS direction,
    COALESCE(sender.email, from_participant.email) AS sender_email,
    matched_roles.matched_roles,
    all_participants.participant_emails
  FROM messages m
  LEFT JOIN contacts sender ON sender.id = m.sender_contact_id
  LEFT JOIN LATERAL (
    SELECT mp.email
    FROM message_participants mp
    WHERE mp.message_id = m.id
      AND mp.participant_type = 'from'
    ORDER BY mp.position ASC
    LIMIT 1
  ) AS from_participant ON TRUE
  JOIN LATERAL (
    SELECT ARRAY_REMOVE(ARRAY_AGG(mp.participant_type), NULL) AS matched_roles
    FROM message_participants mp
    WHERE mp.message_id = m.id
      AND LOWER(COALESCE(mp.email, '')) = LOWER(contact_email)
  ) AS matched_roles ON matched_roles.matched_roles IS NOT NULL
  LEFT JOIN LATERAL (
    SELECT ARRAY_REMOVE(ARRAY_AGG(DISTINCT mp.email), NULL) AS participant_emails
    FROM message_participants mp
    WHERE mp.message_id = m.id
  ) AS all_participants ON TRUE
  ORDER BY m.sent_at DESC
  LIMIT limit_count;
$$ LANGUAGE SQL STABLE;
