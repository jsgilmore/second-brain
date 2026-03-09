# Operations

This document collects the host-side operational commands for the local Second Brain Service stack. The current ingestion source is Gmail.

## Start and inspect

```bash
make up
make ps
make logs
```

Services exposed locally:

- Postgres: `127.0.0.1:5432`
- local API: `127.0.0.1:8080`
- n8n: `127.0.0.1:5678`
- remote MCP profile service: `127.0.0.1:8000`

## Gmail ingestion

Full backfill:

```bash
make gmail-backfill
```

Resume an interrupted backfill:

```bash
make gmail-backfill-resume
```

Last 12 months only:

```bash
make gmail-backfill-12mo
```

Incremental sync after a completed full unfiltered backfill:

```bash
make gmail-incremental
```

For n8n-driven new mail ingest after the initial backfill, see [docs/n8n-gmail-ingest.md](n8n-gmail-ingest.md).

## Resume semantics

Backfill checkpoints are stored in Postgres `sync_state` under `gmail_backfill`.

- resume is page-based, not message-offset based
- a crash may replay at most the last in-flight page
- message upserts prevent duplicate rows
- only successful full unfiltered backfills write the long-lived `gmail` incremental cursor

## Schema upgrades and rehydration

Apply database SQL files in `docker/postgres/init/`:

```bash
make apply-schema
```

Backfill normalized analysis fields from already-stored Gmail `raw_payload`:

```bash
make rehydrate-gmail
```

Use this after schema changes that add derived mail fields such as recipients or header columns.

## Verification

API health:

```bash
curl http://localhost:8080/healthz
```

Manual Gmail payload ingest:

```bash
curl http://localhost:8080/ingest/gmail \
  -H 'Content-Type: application/json' \
  -d @/path/to/full-gmail-message.json
```

Recent messages in Postgres:

```sql
SELECT subject, sent_at
FROM public.messages
ORDER BY sent_at DESC
LIMIT 20;
```

Participant counts:

```sql
SELECT participant_type, count(*)
FROM public.message_participants
GROUP BY participant_type
ORDER BY participant_type;
```

## Runtime files

These paths are local runtime state and should not be treated as source:

- `logs/`
- `.venv/` when recreated for host-side commands
- `.venv.py39.bak/` if retained as a local backup
- `config/gmail-token.json`
- `config/gmail-oauth-client.json`

If you create local temporary analysis files while operating the stack, keep them under `tmp/` rather than in the repo root.
