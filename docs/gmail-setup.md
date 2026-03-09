# Gmail Setup

## 1. Create Google OAuth credentials

In Google Cloud:

1. Create or choose a project.
2. Enable the Gmail API.
3. Create an OAuth client of type `Desktop app`.
4. Download the client JSON.

Place the downloaded file here:

`config/gmail-oauth-client.json`

## 2. Start the local stack

```bash
cp .env.example .env
make up
```

## 3. Configure embeddings

With the default setup, set `OPENAI_API_KEY` in `.env`.

If you plan to use local Ollama embeddings instead, set `EMBEDDING_PROVIDER=ollama` and configure the Ollama values from `.env.example`.

## 4. Run the first backfill

```bash
make gmail-backfill
```

The first host-side `make` command creates `.venv/` automatically and installs the Python dependencies used by the Gmail sync CLI.

If the backfill is interrupted, resume it from the saved checkpoint:

```bash
make gmail-backfill-resume
```

The first run opens a browser-based Google OAuth flow on your local machine and stores the token here:

`config/gmail-token.json`

## 5. Recommended first backfill shapes

Start narrower if your mailbox is large:

```bash
PYTHONPATH=./second-brain-service/src python3 -m second_brain_service.cli gmail-sync backfill \
  --credentials ./config/gmail-oauth-client.json \
  --token ./config/gmail-token.json \
  --query 'newer_than:365d -category:promotions -category:social'
```

Once that works, run the full import:

```bash
PYTHONPATH=./second-brain-service/src python3 -m second_brain_service.cli gmail-sync backfill \
  --credentials ./config/gmail-oauth-client.json \
  --token ./config/gmail-token.json
```

Only that full unfiltered backfill writes the long-lived Gmail incremental cursor. Narrow test runs are safe and do not advance it.
Interrupted backfills save a page checkpoint in Postgres `sync_state`, so resume continues from the last committed page instead of restarting from zero.

## 6. Incremental sync

After the first backfill:

```bash
make gmail-incremental
```

This uses the saved Gmail `historyId` in Postgres `sync_state`.

## 7. Validate data landed

```bash
curl http://localhost:8080/healthz
```

```bash
curl http://localhost:8080/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"receipt from aws","limit":5}'
```

If you upgrade the schema after an earlier backfill and want normalized recipients and headers for already-stored mail:

```bash
make apply-schema
make rehydrate-gmail
```

Useful analysis queries once that completes:

```sql
SELECT *
FROM contact_activity
ORDER BY message_count DESC
LIMIT 25;
```

```sql
SELECT conversation_id, title, message_count, unique_email_count, participant_emails
FROM conversation_analysis
ORDER BY last_message_at DESC
LIMIT 25;
```

```sql
SELECT *
FROM messages_with_contact('someone@example.com', 50);
```

## Current limitations

- Attachment binaries are not downloaded yet.
- Only added messages are handled in incremental sync.
- Gmail label metadata is stored, but labels are not normalized into separate tables yet.
- The default embedding path sends email text to OpenAI for vectorization.
