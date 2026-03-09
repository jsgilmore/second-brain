# Troubleshooting

This guide covers the most common first-run failures and setup mistakes for Second Brain Service with the current Gmail connector.

## `make up` fails or services do not stay up

Check the container state:

```bash
make ps
make logs
```

Common causes:

- Docker Desktop or the Docker daemon is not running.
- Port `5432`, `5678`, `8080`, or `8000` is already in use.
- `.env` is missing or required values such as `POSTGRES_PASSWORD` are blank.

If a port is already in use, either stop the conflicting process or change the matching port value in `.env`.

## `curl http://localhost:8080/healthz` fails

Usually this means the `mcp` container is not healthy yet or failed to start.

Check:

```bash
make ps
make logs
```

If `make up` was successful but the health check still fails:

- wait a few seconds for Postgres startup and retry
- confirm `MCP_API_PORT=8080` in `.env`
- confirm nothing else on your machine is already bound to `8080`

## `make gmail-backfill` fails immediately

Check these first:

- `config/gmail-oauth-client.json` exists
- the file is a Google OAuth `Desktop app` client, not a web client
- Python `3.12` is installed on the host
- `.env` has the required values for your embedding mode

The first host-side `make` command creates `.venv/` automatically. If that step fails, inspect the output for Python or package-install errors and rerun:

```bash
make gmail-backfill
```

## The Google OAuth browser flow does not complete

Common causes:

- you created the wrong Google OAuth client type
- the Gmail API is not enabled in your Google Cloud project
- you are running the command on a machine that cannot open a local browser

Use a Google OAuth `Desktop app` client for local Gmail sync. The token should be written to:

```text
config/gmail-token.json
```

## `OPENAI_API_KEY is not set; embeddings are unavailable`

You are using the default embedding mode.

Fix one of these:

1. Set `OPENAI_API_KEY` in `.env` and rerun the sync.
2. Switch to `EMBEDDING_PROVIDER=ollama` and make sure Ollama is running.
3. Run the sync with `--disable-embeddings` if you want to test ingestion first.

Without embeddings, mail can still be ingested, but semantic search quality will be limited.

## Ollama embeddings fail

Check:

- `EMBEDDING_PROVIDER=ollama`
- `OLLAMA_BASE_URL` points to a reachable Ollama instance
- the configured model exists locally

Useful command:

```bash
make ollama-pull
```

If you are running Ollama on the host and using Docker for the app stack, keep the default `OLLAMA_BASE_URL=http://host.docker.internal:11434` unless your platform requires something different.

## Search returns no results or very weak results

Common causes:

- no mail has been ingested yet
- the backfill was interrupted before useful data landed
- embeddings were disabled during ingest
- the query is too specific for the current mailbox contents

Check service health first:

```bash
curl http://localhost:8080/healthz
```

Then try:

- `make gmail-backfill-resume` if a backfill stopped partway through
- a broader search query such as `invoice`, `contract`, or a sender email
- a new ingest run with embeddings enabled if your first run used `--disable-embeddings`

## `make gmail-incremental` does not behave as expected

Incremental sync depends on a completed full unfiltered backfill.

If your previous run used any of these, it does not establish the long-lived Gmail incremental cursor:

- `--query`
- `--label`
- `--max-messages`

Run one full unfiltered backfill first, then use:

```bash
make gmail-incremental
```

## Remote MCP startup fails

Check that you only start the remote profile when you actually need it:

```bash
docker compose --profile remote up -d mcp_remote
```

If auth is enabled, these values must be set:

- `PUBLIC_BASE_URL`
- `REMOTE_MCP_GOOGLE_CLIENT_ID`
- `REMOTE_MCP_GOOGLE_CLIENT_SECRET`
- `REMOTE_ALLOWED_EMAILS` or `REMOTE_ALLOWED_DOMAINS`

For local-only testing, do not expose the service publicly.

## Common setup mistakes

- Using a Google OAuth `Web application` client for local Gmail sync instead of a `Desktop app` client.
- Forgetting to copy `.env.example` to `.env` before starting the stack.
- Leaving `POSTGRES_PASSWORD` or `N8N_BASIC_AUTH_PASSWORD` at an empty value.
- Assuming `OPENAI_API_KEY` is always required even when `EMBEDDING_PROVIDER=ollama`.
- Starting with `make gmail-incremental` before completing one full unfiltered backfill.
- Expecting ChatGPT to connect directly to `http://localhost:8000/sse`.
- Exposing the remote MCP service without setting an allowlist.

## Still stuck

Use these first:

```bash
make ps
make logs
curl http://localhost:8080/healthz
```

Then review:

- [docs/getting-started.md](getting-started.md)
- [docs/gmail-setup.md](gmail-setup.md)
- [docs/chatgpt-mcp.md](chatgpt-mcp.md)
- [docs/operations.md](operations.md)
