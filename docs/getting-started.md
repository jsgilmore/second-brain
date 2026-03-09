# Getting Started

This guide covers the minimum setup required to run Second Brain Service locally with Gmail as the first supported source, ingest mail from Gmail, and verify search is working.

## 1. Prerequisites

You need:

- Docker with `docker compose`
- Python 3.12 for host-side Gmail sync commands
- A Google account with access to the mailbox you want to index
- A Google Cloud project with the Gmail API enabled
- An OpenAI API key if you want OpenAI embeddings with the default setup

Optional:

- Ollama if you want local embeddings instead of OpenAI
- A public HTTPS URL plus Google OAuth web credentials if you want to expose the remote MCP server to ChatGPT

## 2. Create local config files

Copy the example environment file:

```bash
cp .env.example .env
```

You will also use the `config/` directory for local Gmail OAuth files:

- `config/gmail-oauth-client.json`
- `config/gmail-token.json`

Those files are local secrets and should not be committed.

## 3. Fill in the required environment variables

Edit `.env` and set at least:

### Required for local stack

- `POSTGRES_PASSWORD`
- `N8N_BASIC_AUTH_PASSWORD`

### Required for semantic search with the default embedding setup

- `OPENAI_API_KEY`

If you switch to `EMBEDDING_PROVIDER=ollama`, `OPENAI_API_KEY` is not required.

### Optional for local-only use

- `PUBLIC_BASE_URL`
- `REMOTE_MCP_GOOGLE_CLIENT_ID`
- `REMOTE_MCP_GOOGLE_CLIENT_SECRET`
- `REMOTE_ALLOWED_EMAILS`
- `REMOTE_ALLOWED_DOMAINS`

You only need the `REMOTE_*` values if you plan to run the `mcp_remote` profile and expose it over HTTPS.

Values that usually do not need to change for a first local run:

- `POSTGRES_DB=brain`
- `POSTGRES_USER=brain`
- `POSTGRES_PORT=5432`
- `MCP_API_PORT=8080`
- `MCP_REMOTE_PORT=8000`
- `N8N_PORT=5678`
- `OPENAI_EMBEDDING_MODEL=text-embedding-3-large`

## 4. Create Gmail OAuth credentials

In Google Cloud:

1. Create or choose a project.
2. Enable the Gmail API.
3. Create an OAuth client of type `Desktop app`.
4. Download the client JSON.

Place the downloaded file at:

```text
config/gmail-oauth-client.json
```

For more detail, see [docs/gmail-setup.md](gmail-setup.md).

## 5. Start the local services

```bash
make up
```

Verify the HTTP API is up:

```bash
curl http://localhost:8080/healthz
```

## 6. Run the first Gmail backfill

Run the host-side backfill:

```bash
make gmail-backfill
```

The first host-side `make` command creates `.venv/` automatically and installs the Python dependencies used by the Gmail sync CLI.

On the first run:

- a browser window opens for Google OAuth
- the token is saved to `config/gmail-token.json`

If the backfill is interrupted:

```bash
make gmail-backfill-resume
```

If you want to start with a smaller mailbox slice first:

```bash
make gmail-backfill-12mo
```

## 7. Verify that search works

After some mail has been indexed:

```bash
curl http://localhost:8080/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"invoice from stripe","limit":5}'
```

If you ingest without embeddings, semantic search will be limited until embeddings are generated.

## 8. Optional: choose your embedding mode

### OpenAI embeddings

Default setup:

- `EMBEDDING_PROVIDER=openai`
- `OPENAI_API_KEY` must be set

### Ollama embeddings

If you want local embeddings instead:

- set `EMBEDDING_PROVIDER=ollama`
- set `OLLAMA_BASE_URL`
- set `OLLAMA_EMBEDDING_MODEL`
- ensure Ollama is running and reachable

### No embeddings

You can still ingest mail without embeddings by using:

```bash
PYTHONPATH=./second-brain-service/src python3 -m second_brain_service.cli gmail-sync backfill \
  --credentials ./config/gmail-oauth-client.json \
  --token ./config/gmail-token.json \
  --disable-embeddings
```

## 9. Optional: remote MCP for ChatGPT

Only do this when local ingestion and search are already working.

You need:

- a public HTTPS URL
- `PUBLIC_BASE_URL`
- `REMOTE_MCP_GOOGLE_CLIENT_ID`
- `REMOTE_MCP_GOOGLE_CLIENT_SECRET`
- `REMOTE_ALLOWED_EMAILS` or `REMOTE_ALLOWED_DOMAINS`

Then start the remote profile:

```bash
docker compose --profile remote up -d mcp_remote
```

For the full remote setup flow, see [docs/chatgpt-mcp.md](chatgpt-mcp.md).

## 10. Optional: n8n-triggered Gmail ingest

After the initial backfill, you can configure n8n to push newly received mail into the same ingest path.

See [docs/n8n-gmail-ingest.md](n8n-gmail-ingest.md).

## 11. Where to go next

- Operations and recovery: [docs/operations.md](operations.md)
- Gmail OAuth details: [docs/gmail-setup.md](gmail-setup.md)
- Remote MCP exposure: [docs/chatgpt-mcp.md](chatgpt-mcp.md)
- Troubleshooting and setup mistakes: [docs/troubleshooting.md](troubleshooting.md)
- Security notes: [docs/security-hardening.md](security-hardening.md)
