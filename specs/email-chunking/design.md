# Email Chunking Design

This document proposes a design that satisfies the requirements in [requirements.md](requirements.md).

The design keeps the current Gmail ingestion model and database-centric retrieval stack, but replaces coarse body chunking with section-aware, token-aware chunk generation and richer chunk metadata.

## Design summary

The new design introduces a staged chunking pipeline:

1. normalize and preserve structure
2. segment the message into email-aware sections
3. build coherent chunk candidates from those sections
4. split oversized candidates using token-aware rules
5. attach structural metadata
6. embed the final chunks

The design is intentionally incremental:

- Phase 1 improves chunk quality and metadata while keeping the existing `message_chunks` table usable
- Phase 2 can make fuller use of new metadata in retrieval and context expansion

## Design principles

1. Semantic boundaries beat maximum-size packing.
2. Message structure is valuable retrieval data and should be preserved.
3. Current authored content and quoted history should not be mixed by default.
4. Rich metadata is cheaper than rebuilding context later.
5. Parsing uncertainty should degrade safely rather than halt ingestion.
6. Rehydration from stored `raw_payload` must remain possible.

## Current-state constraints

The current system:

- normalizes Gmail messages in `second-brain-service/src/second_brain_service/ingest/gmail_sync.py`
- builds chunks in `second-brain-service/src/second_brain_service/search/embeddings.py`
- stores chunks in `message_chunks`
- retrieves via lexical plus vector search in `second-brain-service/src/second_brain_service/store/mail_repository.py`

The design should minimize disruption to:

- Gmail backfill and incremental sync
- current search endpoints and MCP tools
- existing rehydration workflow

## Proposed architecture

### New logical pipeline

Introduce a dedicated chunking module, for example:

- `second-brain-service/src/second_brain_service/search/chunking.py`

This module owns the full chunk-preparation pipeline and is called by Gmail normalization.

The flow becomes:

1. `extract_body(...)` returns cleaned text and HTML as today
2. `chunking.prepare_message_sections(...)` builds section objects
3. `chunking.build_chunks(...)` builds final chunk rows with metadata
4. `EmbeddingClient` embeds finalized chunk text
5. `db._upsert_message_record(...)` stores chunks and metadata

### Section model

Add an internal section representation such as:

```python
{
  "section_index": 0,
  "section_type": "body" | "quote" | "forward" | "signature" | "footer" | "boilerplate" | "unknown",
  "text": "...",
  "source_role": "current_author" | "quoted_author" | "unknown",
  "message_level_position": 0,
  "attributes": {
    "reply_depth": 0,
    "boundary_reason": "paragraph_break"
  }
}
```

This object is internal only. It is not necessarily stored directly.

### Chunk model

Build chunks from one or more adjacent sections or paragraph groups. A stored chunk should contain:

```python
{
  "chunk_index": 3,
  "text": "...",
  "embedding_model": "...",
  "embedding": [...],
  "metadata": {
    "section_type": "body",
    "section_index": 1,
    "position_start": 2,
    "position_end": 3,
    "source_role": "current_author",
    "is_quote": false,
    "prev_chunk_index": 2,
    "next_chunk_index": 4,
    "suppressed": false
  }
}
```

This fits the current storage model because `message_chunks` already has a `metadata` column.

## Parsing and sectioning strategy

### Step 1. Preserve message structure

Replace the current flattening approach with structure-preserving normalization:

- preserve paragraph breaks
- preserve blank-line section boundaries
- preserve bullet/list line grouping
- preserve visible reply separators such as `On ... wrote:`
- preserve forwarded-message headers when detectable

Text cleanup should still remove noisy artifacts, but must not collapse the full body into one flat line before sectioning.

### Step 2. Detect section boundaries

Sectioning should use deterministic heuristics in the first version.

Detection rules should cover:

- quoted reply markers
- forwarded-message markers
- signature separators like `--`
- common footer and unsubscribe patterns
- obvious disclaimer blocks

If a section cannot be classified with confidence, assign `unknown` and continue.

### Step 3. Build coherent chunk candidates

Within each section:

- use paragraph groups as the default chunk unit
- keep bullet lists together where reasonable
- keep quoted blocks separate from current content
- avoid merging dissimilar section types

Heuristics should prefer topical coherence over maximizing chunk size.

## Token-aware splitting

### Token budget

Introduce configuration values such as:

- `CHUNK_TARGET_TOKENS`
- `CHUNK_MAX_TOKENS`
- `CHUNK_OVERLAP_TOKENS`

The current character-based config can remain temporarily as a fallback or compatibility layer, but the primary behavior should be token-aware.

### Token counting

Use a tokenizer that matches or reasonably approximates the embedding model family.

The splitting logic should:

1. attempt to fit whole paragraph groups inside `CHUNK_TARGET_TOKENS`
2. split oversized groups at sentence boundaries
3. use a hard fallback only when a single sentence or line still exceeds limits

### Safety margin

Set `CHUNK_MAX_TOKENS` below the actual embedding model limit to avoid edge-case failures during ingestion.

The exact default should be chosen during implementation, but the design assumes a meaningful margin rather than operating at the hard maximum.

## Boilerplate policy

### Default behavior

The first implementation should distinguish between:

- content to drop before chunking
- content to retain but mark as low-value

Recommended policy:

- drop obvious tracking fragments and empty CTA remnants
- keep signatures and disclaimers only if classification confidence is low
- otherwise mark low-value sections as `suppressed=true` in chunk metadata and skip embedding them

This satisfies retrieval quality without losing all auditability.

## Embedding policy

### Chunk text

Chunk text should be embedded as finalized chunk content, not as a single flattened whole-message body.

The chunk text may include lightweight context prefixes only if they are consistent and helpful, for example:

- normalized subject
- section role label

This should be used conservatively. The primary signal should remain the chunk body itself.

### Embedding failures

Embedding failures must remain non-fatal at the chunk level. The current fallback behavior should be retained and adapted to the new chunker.

## Storage design

### Existing schema usage

The current `message_chunks` table can support the new design without a hard schema break if chunk metadata is stored in `metadata`.

Minimum stored metadata:

- `section_type`
- `section_index`
- `source_role`
- `is_quote`
- `suppressed`
- `prev_chunk_index`
- `next_chunk_index`
- `position_start`
- `position_end`

### Optional schema improvements

If retrieval or SQL filtering becomes awkward, add explicit columns later for:

- `section_type`
- `source_role`
- `suppressed`

These are optimizations, not prerequisites for the first implementation.

## Retrieval changes

### Phase 1 retrieval behavior

Keep current lexical plus semantic search, but improve result quality because chunks are better formed.

Minimal retrieval change:

- prefer non-suppressed chunks when ranking or returning results

### Phase 2 retrieval behavior

Add context expansion and relation-aware response assembly:

1. find the best chunk matches
2. fetch neighboring chunks from the same message
3. optionally fetch nearby messages in the same conversation
4. present a result with both precise evidence and local context

This design depends on chunk metadata but does not require all retrieval changes in the first implementation pass.

## Rehydration and migration

### Rehydration strategy

Reuse stored `raw_payload` to regenerate chunks for already ingested messages.

This means:

- no new Gmail fetch is required
- the `rehydrate-gmail` path can rebuild chunks under the new logic
- rehydration should replace old chunks for each message deterministically

### Backward compatibility

Existing messages without the new metadata should still remain queryable during rollout.

The migration path should support:

- new ingests using the new chunker
- existing ingests being rehydrated later

## Observability and validation

Add metrics or structured logs for:

- sections detected per message
- chunks produced per message
- chunks suppressed per message
- oversized section fallback usage
- embedding failures by section type

For evaluation, prepare a validation set of representative emails:

- short personal email
- long work email with multiple topics
- reply chain with quoted history
- forwarded thread
- newsletter or promotional email

## Requirement mapping

- `R1` is satisfied by structure-preserving normalization and section-first parsing.
- `R2` is satisfied by explicit section detection and classification.
- `R3` is satisfied by paragraph-group and reply-turn chunk construction.
- `R4` is satisfied by token-aware target and max budgets.
- `R5` is satisfied by section-local overlap only.
- `R6` is satisfied by chunk metadata stored in `message_chunks.metadata`.
- `R7` is satisfied by neighbor linkage and message/thread identifiers.
- `R8` is satisfied by suppression or removal of boilerplate sections.
- `R9` is satisfied by deterministic heuristic parsing and stable ordering.
- `R10` is satisfied by `unknown` section fallback and non-fatal embedding behavior.

## Risks and tradeoffs

### More chunks per message

This design will likely increase chunk counts and embedding cost.

Mitigation:

- suppress low-value sections
- tune token budgets
- evaluate chunk count on representative mail before full rehydration

### Heuristic misclassification

Reply separators and signatures vary widely across senders and clients.

Mitigation:

- deterministic but conservative heuristics
- safe fallback to `unknown`
- validation corpus plus regression tests

### Retrieval complexity

Chunk metadata enables richer retrieval, but retrieval assembly may become more complex.

Mitigation:

- keep Phase 1 retrieval changes minimal
- defer relation-aware expansion to a later phase

## Recommended rollout

1. implement the new chunking module and metadata generation
2. switch Gmail ingestion to use it
3. validate on a representative corpus
4. rehydrate stored messages
5. add retrieval-side context expansion after chunk quality is proven
