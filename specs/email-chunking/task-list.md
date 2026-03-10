# Email Chunking Task List

This document breaks the design in [design.md](design.md) into implementation tasks.

The task list is ordered to realize the design with controlled risk and clear verification points.

## Implementation status snapshot

Status as of 2026-03-10.

- [x] Phase 1 foundations are implemented.
- [x] Phase 2 section-aware parsing is implemented.
- [x] Phase 3 coherent chunk building is implemented.
- [x] Phase 4 metadata and storage integration is implemented.
- [x] Phase 5 is implemented.
- [x] Phase 6 is implemented.
- [~] Phase 7 is partially implemented.

Remaining implementation focus before this feature is considered complete:

- [ ] Add local context expansion around matched chunks.
- [ ] Add optional thread-level expansion driven by conversation metadata.

## Phase 1: Prepare the foundations

### 1. Define chunking configuration

- [x] add config entries for token-oriented chunk sizing and overlap
- [x] keep compatibility with existing config where needed during transition
- [x] document default values and the meaning of each setting

Exit criteria:

- chunking behavior is configurable without code edits
- defaults are defined for local development and backfill use

### 2. Create a dedicated chunking module

- [x] add a new module such as `second-brain-service/src/second_brain_service/search/chunking.py`
- [x] move chunk-construction responsibility out of `embeddings.py`
- [x] keep the public interface small and deterministic

Suggested interface:

- `prepare_message_sections(subject, body_text, body_html, headers) -> list[section]`
- `build_message_chunks(subject, body_text, body_html, headers, embedding_client) -> list[chunk]`

Exit criteria:

- Gmail normalization can call the new module without changing external behavior yet

### 3. Add token counting support

- [x] choose a tokenizer strategy appropriate for the embedding model
- [x] implement deterministic token estimation helpers
- [x] add fallback behavior when tokenization fails

Exit criteria:

- chunk sizing can use token budgets rather than characters

## Phase 2: Implement section-aware parsing

### 4. Preserve structure through normalization

- [x] stop flattening the full message body into a single whitespace stream before chunking
- [x] preserve paragraph and blank-line boundaries needed by sectioning
- [x] keep existing noise cleanup only where it does not destroy structure

Exit criteria:

- test inputs retain paragraph structure after normalization

### 5. Implement email section detection

- [x] detect primary body sections
- [x] detect quoted reply blocks
- [x] detect forwarded-message blocks
- [x] detect signatures and footer-like sections
- [x] detect obvious boilerplate sections when confidence is high

Exit criteria:

- representative messages produce stable section sequences with explicit section types

### 6. Add safe fallback classification

- [x] classify uncertain regions as `unknown`
- [x] ensure odd formatting does not stop ingestion

Exit criteria:

- no sectioning path raises avoidable ingestion-time exceptions on malformed or unusual content

## Phase 3: Implement coherent chunk building

### 7. Build paragraph-group chunk candidates

- [x] group adjacent paragraphs within the same section
- [x] keep bullet lists together where reasonable
- [x] avoid mixing different section types in a single chunk

Exit criteria:

- chunk candidates align with human-visible message structure on representative examples

### 8. Add token-aware splitting for oversized candidates

- [x] split oversized candidates on paragraph boundaries first
- [x] then split on sentence boundaries
- [x] use a deterministic hard fallback only when required

Exit criteria:

- all produced chunks stay within configured token limits
- large sections split predictably across runs

### 9. Add section-local overlap

- [x] implement overlap only within the same semantic section
- [x] keep overlap configurable and conservative

Exit criteria:

- neighboring chunks preserve continuity without merging unrelated concepts

## Phase 4: Attach metadata and storage behavior

### 10. Enrich chunk metadata

- [x] store section type
- [x] store section index
- [x] store source role
- [x] store quote/body flags
- [x] store previous and next chunk linkage
- [x] store local position information
- [x] store suppression flag

Exit criteria:

- each chunk can be traced to message structure and neighboring chunks

### 11. Suppress or skip low-value chunks

- [x] decide which sections are dropped entirely
- [x] mark retained low-value chunks as suppressed
- [x] skip embeddings for suppressed chunks if design choice is confirmed

Exit criteria:

- signatures, disclaimers, and boilerplate have limited retrieval influence

### 12. Integrate with existing database writes

- [x] keep using `message_chunks.metadata` for first-pass storage
- [x] ensure old and new chunks remain compatible during rollout
- [x] verify rehydration replaces message chunks deterministically

Exit criteria:

- no schema break is required for first implementation

## Phase 5: Wire into ingestion and rehydration

### 13. Replace the current chunking call site

- [x] update Gmail normalization to use the new chunking module
- [x] keep embedding behavior chunk-level and non-fatal

Exit criteria:

- new Gmail ingests use section-aware chunking end to end

### 14. Update rehydration path

- [x] ensure `rehydrate-gmail` rebuilds chunks using the new logic
- [x] verify raw Gmail payloads contain enough data for stable regeneration

Exit criteria:

- existing stored messages can be re-chunked without refetching Gmail

## Phase 6: Validation and evaluation

### 15. Build a representative validation corpus

- [x] collect examples for short mail
- [x] long multi-topic mail
- [x] reply chains
- [x] forwarded threads
- [x] newsletters and promotions

Exit criteria:

- the corpus covers the main failure modes discussed in the requirements

### 16. Add automated tests

- [x] unit tests for section detection heuristics
- [x] unit tests for token-aware splitting
- [x] regression tests for deterministic chunk output
- [x] tests for suppressed-section handling
- [x] regression tests for forwarded-content section handling
- [x] regression tests for suppressed-chunk retrieval filtering

Exit criteria:

- chunking behavior is testable and stable

### 17. Add operator-facing diagnostics

- [x] log section and chunk counts
- [x] log fallback splitting usage
- [x] log suppressed chunk counts
- [x] log embedding failures without aborting ingestion
- [x] add a stable operator summary for chunking skips, parser fallbacks, and per-message rechunk failures

Exit criteria:

- backfill and rehydration runs provide enough visibility to debug chunking behavior

### 18. Compare retrieval quality before broad rollout

- [x] run representative queries against old and new chunking
- [x] inspect whether results are more precise and easier to explain
- [x] review chunk count and embedding cost impact

Exit criteria:

- there is evidence the redesign improves retrieval enough to justify rollout

## Phase 7: Retrieval improvements

### 19. Prefer non-suppressed chunks in results

- [x] update chunk retrieval and ranking logic to avoid promoting suppressed chunks unless necessary

Exit criteria:

- low-value content appears less often in search results

### 20. Add local context expansion

- [ ] fetch neighboring chunks around a matched chunk
- [ ] include message-local context in result assembly where useful

Exit criteria:

- results can show both the precise hit and surrounding message context

### 21. Add optional thread-level expansion

- [ ] use conversation IDs and sent times to fetch nearby related messages
- [ ] keep this optional to avoid over-expanding every result

Exit criteria:

- thread-aware follow-up context is available for searches that need it

## Sequencing recommendation

Recommended execution order:

1. complete Phases 1 through 4
2. wire the new chunker into ingestion and rehydration
3. validate chunk quality and operational cost
4. rehydrate stored mail
5. improve retrieval behavior using the new metadata

## Out of scope for the first implementation pass

- a learned section classifier
- LLM-based chunking during ingestion
- graph-style relationship extraction across messages
- a hard schema migration solely to normalize chunk metadata into first-class columns
