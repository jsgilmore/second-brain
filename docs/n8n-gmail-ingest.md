# n8n Gmail Ingest

Use this when you want n8n to handle new-mail events, while the Python service keeps ownership of normalization, chunking, storage, and embeddings.

## Goal

The flow should stay:

1. n8n detects a new Gmail message.
2. n8n fetches the full Gmail API message payload for that message.
3. n8n POSTs that payload to the local API.
4. The API normalizes and upserts it with the same code path used by `gmail_sync.py`.

This avoids creating a second mail schema inside n8n.

## Endpoint

From inside the `n8n` container, call:

```text
http://mcp:8080/ingest/gmail
```

From the host machine, the same endpoint is:

```text
http://localhost:8080/ingest/gmail
```

## Request shape

Send the full Gmail API message JSON as the request body.

Accepted shapes:

- the raw Gmail message object itself
- `{ "message": <gmail-message> }`
- `{ "gmail_message": <gmail-message> }`
- `{ "raw_payload": <gmail-message> }`

Optional flag:

- `disable_embeddings: true` if you want to store the message without vectorization for a specific request

If the request only contains Gmail metadata and not the full `payload`, the API returns a validation error. In n8n, add a Gmail fetch step after the trigger so the body, headers, and MIME parts are present.

## Recommended n8n flow

1. Gmail Trigger: watch for new messages.
2. Gmail message fetch step: load the full Gmail message for the triggered id.
3. HTTP Request:
   - method: `POST`
   - URL: `http://mcp:8080/ingest/gmail`
   - body: the full Gmail message JSON from the previous step
   - content type: JSON

An importable workflow is included at [docs/n8n-workflows/gmail-new-mail-to-second-brain.json](docs/n8n-workflows/gmail-new-mail-to-second-brain.json).

After importing it into n8n:

1. attach your Gmail credential to the `Gmail Trigger`
2. attach the same Gmail credential to `Fetch Full Gmail Message`
3. activate the workflow

The API response includes the stored message id, conversation id, chunk count, and Gmail history id.

## Example

```bash
curl http://localhost:8080/ingest/gmail \
  -H 'Content-Type: application/json' \
  -d @/path/to/full-gmail-message.json
```

Example success response:

```json
{
  "status": "ok",
  "message_id": "2dbd0f7d-5b7d-4b15-a7cc-65ecdf1dd5f9",
  "conversation_id": "d8cb697d-c2ab-4ef9-a353-f7a8f7d405f8",
  "chunk_count": 3,
  "attachment_count": 1,
  "participant_count": 4,
  "source": "gmail",
  "external_id": "1960abc123def456",
  "conversation_external_id": "1960abc123def000",
  "gmail_history_id": "987654"
}
```

## Operational notes

- Run a normal full Gmail backfill first so your archive and `sync_state.gmail.history_id` are initialized.
- If that Gmail cursor already exists, `/ingest/gmail` advances it when a newer Gmail `historyId` arrives through n8n.
- Upserts are idempotent on `(source, external_id)`, so a later manual incremental sync can safely replay already-ingested messages.
