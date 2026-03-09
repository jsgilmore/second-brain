# Architecture Notes

## Current focus

This repo is now Gmail-first.

The main service folder is `second-brain-service/`. It contains the mail ingestion/search service as a whole, not only MCP-specific code.

- `Postgres + pgvector` is the durable mail archive
- `gmail_sync.py` handles Gmail backfill and incremental sync
- `mcp` serves the local ingestion and search API
- `mcp_remote` serves the MCP surface for ChatGPT and other MCP clients
- `OpenAI` serves remote embeddings with `text-embedding-3-large`
- `n8n` can trigger on new Gmail mail and POST the full Gmail payload into `/ingest/gmail`

## Core schema

- `contacts`: email senders keyed by source plus email address
- `conversations`: Gmail threads
- `messages`: one normalized row per Gmail message
- `attachments`: attachment metadata
- `message_chunks`: chunked email text and embeddings
- `sync_state`: sync cursors such as Gmail `historyId`

## Gmail mapping

- `conversation_external_id`: Gmail `threadId`
- `external_id`: Gmail message `id`
- `sender.external_id`: parsed sender email address
- `raw_payload`: full Gmail API message response
- `metadata.label_ids`: Gmail labels stored per message
- the same normalization code is used for both direct Gmail sync and n8n-triggered Gmail ingest

## Retrieval strategy

`POST /search` and the MCP `search` tool use hybrid retrieval:

1. Postgres full-text search over `subject` and `body_text`
2. semantic search over `message_chunks.embedding` if embeddings exist
3. reciprocal-rank fusion in the application layer

This gives you reasonable results even before the whole mailbox has embeddings.

## Embedding strategy

For the current scaffold:

- embeddings are created remotely during Gmail ingestion through OpenAI
- the default embedding model is `text-embedding-3-large`
- chunks are built from `subject + body_text`

Once you settle on one model and dimension:

- migrate `message_chunks.embedding` to a fixed dimension
- add an HNSW index
- optionally create a dedicated vector-only materialized search table

## Remote MCP shape

The remote MCP server exposes:

- `search(query, limit)`
- `fetch(message_id)`
- `fetch_thread(conversation_id, limit)`
- `status()`

That is the minimum useful surface for ChatGPT to search and inspect your mail corpus.
