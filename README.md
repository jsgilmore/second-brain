# Second Brain Service

This repo is a self-hosted second-brain service for bringing personal work context into one searchable system.

The goal is to help a user pull together different sources of information, make sense of ongoing work, and support assistant-style workflows over that combined context.

Today, Gmail is the first fully implemented source. The service is structured to grow into additional sources over time, including things like Slack messages, notes, calendars, and other messaging systems.

Current stack:

- `Postgres + pgvector` stores normalized source records and chunk embeddings
- `mcp` exposes an HTTP API for ingestion and search
- `mcp_remote` exposes an MCP server for ChatGPT or other MCP clients
- `OpenAI text-embedding-3-large` provides remote embeddings
- `n8n` can push new Gmail messages into the same normalization and vectorization path used by the Gmail backfill

The core design is simple:

1. Source data is pulled or received through connector-specific ingestion paths.
2. Records are normalized into Postgres.
3. Searchable text is chunked and optionally embedded.
4. The MCP server answers search and fetch requests over the resulting knowledge base.

## Working with agents

This repo includes agent-specific workflow guidance in [AGENTS.md](AGENTS.md).

For new features, the default workflow is spec-first:

- create `specs/<feature-name>/requirements.md`
- create `specs/<feature-name>/design.md`
- create `specs/<feature-name>/task-list.md`
- stop for review before implementation

## Repo map

The current folder layout is now organized around the main service:

- `second-brain-service/`: the main Python service; it contains the shared storage, search, HTTP, and MCP code plus the current Gmail connector
- `docker/`: Postgres bootstrap SQL and container-side setup
- `config/`: local OAuth client and token files used on the host machine
- `docs/`: setup, architecture, security, and operations notes
- `logs/`: local run logs

The old `mcp_server/` compatibility shim has been removed. The canonical entrypoint is under `second-brain-service/`.

## What is in the repo

- `docker-compose.yml`: Postgres, n8n, local API, and remote MCP services
- `docker/postgres/init/001_init.sql`: schema, text-search functions, sync-state table
- `docs/getting-started.md`: end-to-end setup guide for local use
- `docs/troubleshooting.md`: common first-run failures and setup mistakes
- `second-brain-service/src/second_brain_service/ingest/gmail_sync.py`: Gmail backfill and incremental sync logic
- `second-brain-service/src/second_brain_service/store/mail_repository.py`: normalized mail persistence and retrieval
- `second-brain-service/src/second_brain_service/interfaces/remote_mcp.py`: remote MCP tools for `search`, `fetch`, `fetch_thread`, and `status`
- `docs/gmail-setup.md`: Google Cloud OAuth and first sync steps
- `docs/chatgpt-mcp.md`: exposing the remote MCP service for ChatGPT
- `docs/operations.md`: operational commands, resume/recovery flow, and database upgrade tasks
- `docs/cleanup-plan.md`: current structure and compatibility notes

## Services

- Postgres: `localhost:5432`
- n8n: `http://localhost:5678`
- local API: `http://localhost:8080`
- remote MCP endpoint: `http://localhost:8000/sse`

All published ports are bound to `127.0.0.1` only. Nothing in this stack is internet-reachable by default. ChatGPT cannot connect to a local-only endpoint, so you will need to expose only the remote MCP service through HTTPS before adding it inside ChatGPT.
The `mcp_remote` service is behind the Docker `remote` profile and does not start during normal local use.

## Quick start

If you are using this repo for the first time, start with [docs/getting-started.md](docs/getting-started.md).

1. Copy the env template.

```bash
cp .env.example .env
```

2. Set at least:

- `POSTGRES_PASSWORD`
- `N8N_BASIC_AUTH_PASSWORD`
- `OPENAI_API_KEY` if you keep the default `EMBEDDING_PROVIDER=openai`

If you switch to `EMBEDDING_PROVIDER=ollama`, you do not need `OPENAI_API_KEY`.

For a first local run, the defaults for ports, database name/user, and embedding model are already usable from `.env.example`.

Only set remote MCP values when you are ready to expose the remote profile:

- `PUBLIC_BASE_URL`
- `REMOTE_MCP_GOOGLE_CLIENT_ID`
- `REMOTE_MCP_GOOGLE_CLIENT_SECRET`
- `REMOTE_ALLOWED_EMAILS` or `REMOTE_ALLOWED_DOMAINS`

3. Start the local stack.

```bash
make up
```

4. Verify the API is live.

```bash
curl http://localhost:8080/healthz
```

5. Follow [docs/gmail-setup.md](docs/gmail-setup.md) and place your Google OAuth desktop client file at:

`config/gmail-oauth-client.json`

6. Run the first Gmail backfill from the host machine:

```bash
make gmail-backfill
```

The first host-side `make` command creates `.venv/` automatically and installs the Python dependencies needed for the Gmail sync CLI.

If a backfill is interrupted, resume it from the saved checkpoint:

```bash
make gmail-backfill-resume
```

For the last 12 months only:

```bash
make gmail-backfill-12mo
```

7. Test search once the sync completes:

```bash
curl http://localhost:8080/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"invoice from stripe","limit":5}'
```

8. If you want n8n to keep indexing newly received mail after the initial backfill, follow [docs/n8n-gmail-ingest.md](docs/n8n-gmail-ingest.md).

If setup fails, see [docs/troubleshooting.md](docs/troubleshooting.md).

## Current Gmail connector

The Gmail sync command supports:

- `backfill`: import the full mailbox or a filtered subset
- `incremental`: import newly added mail using Gmail `historyId`

Interrupted backfills can resume from the last saved page checkpoint in `sync_state` using `--resume`. The checkpoint is page-based, so a crash may replay at most the last in-flight page; message upserts prevent duplicates.

Examples:

```bash
PYTHONPATH=./second-brain-service/src python3 -m second_brain_service.cli gmail-sync backfill \
  --credentials ./config/gmail-oauth-client.json \
  --token ./config/gmail-token.json
```

```bash
PYTHONPATH=./second-brain-service/src python3 -m second_brain_service.cli gmail-sync backfill \
  --credentials ./config/gmail-oauth-client.json \
  --token ./config/gmail-token.json \
  --query 'newer_than:365d -category:promotions' \
  --max-messages 5000
```

```bash
PYTHONPATH=./second-brain-service/src python3 -m second_brain_service.cli gmail-sync incremental \
  --credentials ./config/gmail-oauth-client.json \
  --token ./config/gmail-token.json
```

With the default setup, the Gmail connector creates embeddings through OpenAI using `text-embedding-3-large`. If `OPENAI_API_KEY` is missing, mail can still be ingested with `--disable-embeddings`, but semantic search will not work until you generate embeddings.
Only a full unfiltered backfill saves the Gmail incremental cursor in `sync_state`. Trial runs with `--query`, `--label`, or `--max-messages` do not advance the cursor.

## Data model

The current source-specific schema is Gmail-oriented. Each Gmail message is stored as:

- one `messages` row with subject, body text, HTML, key RFC headers, raw Gmail payload, and metadata
- one `conversations` row keyed by Gmail thread ID
- one sender row in `contacts` when possible
- zero or more `message_participants` rows for `from`, `reply_to`, `to`, `cc`, and `bcc`
- zero or more `attachments` metadata rows
- zero or more `message_chunks` rows for vector search

Sync cursor state is stored in `sync_state` under the `gmail` key.

To upgrade an existing database in place after pulling schema changes:

```bash
make apply-schema
make rehydrate-gmail
```

For higher-level analysis in SQL clients like TablePlus, the database also exposes:

- `message_analysis`: one row per message with normalized sender and recipient rollups
- `conversation_analysis`: one row per conversation with participant and sender aggregates
- `contact_activity`: per-email activity summary across sent and received roles
- `messages_with_contact(email, limit)`: helper function for relationship-level message lookup

## Search surfaces

### HTTP API

- `GET /healthz`
- `POST /ingest/gmail`
- `POST /search`
- `GET /messages/<message_id>`
- `GET /conversations/<conversation_id>/messages`

`POST /ingest/gmail` expects a full Gmail API message object or a wrapper like:

```json
{
  "message": {
    "id": "gmail-message-id",
    "threadId": "gmail-thread-id",
    "payload": {}
  }
}
```

The service normalizes the Gmail payload, chunks the body, creates embeddings when enabled, and writes through the same database path used by `gmail_sync.py`.

`POST /search` expects:

```json
{
  "query": "contract renewal with Acme",
  "limit": 8
}
```

The service runs hybrid retrieval:

- Postgres full-text search over subject and body
- vector search over embedded chunks when embeddings are available

### MCP tools

The MCP server exposes:

- `search(query, limit=8)`
- `search_chunks(query, limit=8)`
- `fetch(message_id)`
- `fetch_thread(conversation_id, limit=200)`
- `status()`
- `recent_mail(limit=20, subject_query=None, sender_email=None, participant_email=None)`
- `contacts(limit=20, query=None)`
- `contact_messages(contact_email, limit=20)`
- `investigate(question, limit=12)`

For local stdio MCP clients:

```bash
make mcp-stdio
```

For remote MCP clients, the service is available on `http://localhost:8000/sse` before you place it behind HTTPS.
Start it only when you are ready to expose and configure the remote path:

```bash
docker compose --profile remote up -d mcp_remote
```

## Remote MCP authentication

The remote MCP server is now fail-closed by default:

- `REMOTE_MCP_AUTH_REQUIRED=true`
- it requires Google OAuth on the remote MCP endpoint
- it requires an explicit allowlist through `REMOTE_ALLOWED_EMAILS` or `REMOTE_ALLOWED_DOMAINS`

Recommended configuration for a single-user setup:

```dotenv
PUBLIC_BASE_URL=https://mail-mcp.example.com
REMOTE_MCP_AUTH_REQUIRED=true
REMOTE_MCP_GOOGLE_CLIENT_ID=your-web-oauth-client-id.apps.googleusercontent.com
REMOTE_MCP_GOOGLE_CLIENT_SECRET=your-web-oauth-client-secret
REMOTE_ALLOWED_EMAILS=you@gmail.com
```

Use a separate Google OAuth `Web application` client for the remote MCP server. Do not reuse the Gmail desktop OAuth client used for mailbox ingestion.

If you want to smoke-test the remote MCP server locally before wiring up Google OAuth, you can temporarily set:

```dotenv
REMOTE_MCP_AUTH_REQUIRED=false
```

That allows the SSE server to start without OAuth for local-only testing. Do not expose that configuration on a public URL.

## Notes

- `message_chunks.embedding` is intentionally left as a generic `vector` column for early iteration. Once you settle on one embedding model, add a fixed-dimension index migration.
- The Gmail sync stores attachment metadata only. It does not download attachment file bodies yet.
- The Gmail sync uses desktop OAuth on the host, which is the most practical first pass for a local self-hosted deployment.

## Open Source

This project is licensed under [Apache-2.0](LICENSE).
- The always-on containers do not mount `./config`, so your Gmail OAuth client and token files stay on the host and are not exposed to the remote MCP process.
- The default embedding path is remote OpenAI `text-embedding-3-large`, so email content used for embeddings is sent to OpenAI.
