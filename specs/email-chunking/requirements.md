# Email Chunking Requirements

This document defines the requirements for redesigning email chunking and related retrieval behavior in this repository.

The goal is to improve retrieval quality for Gmail messages by producing chunks that better preserve concepts, sections, authorship, and thread context than the current character-window approach.

## Problem statement

The current chunking logic is simple and operationally cheap, but it is too coarse for concept-oriented retrieval:

- it flattens structure that matters in email
- it splits on character count rather than semantic boundaries
- it can mix unrelated ideas in the same chunk
- it does not explicitly model relationships between chunks, messages, and threads

This leads to weaker semantic retrieval, especially for long emails, newsletters, and multi-turn reply chains.

## Goals

The redesigned chunking system must:

1. produce semantically coherent retrieval units
2. preserve useful email structure
3. separate current-message content from quoted history and boilerplate
4. improve the ability to relate chunks back to message and thread context
5. remain operationally practical for mailbox-scale ingestion

## Non-goals

This work does not need to:

- solve general document parsing for all file types
- build a full knowledge graph
- perfectly classify every email section from day one
- summarize messages during ingestion
- redesign the whole search stack beyond what is necessary to exploit better chunks

## Users and use cases

### Primary user

- a user searching their mailbox through HTTP or MCP for facts, requests, decisions, themes, and context

### Secondary user

- an operator running backfills, resumes, rehydration, and validation who needs predictable ingestion behavior

## User stories

1. As a user, I want a search for a specific topic to return the exact relevant section of an email instead of a large mixed chunk, so I can quickly understand why the result matched.
2. As a user, I want the system to distinguish the latest authored message text from quoted reply history, so I do not get matches dominated by old quoted content.
3. As a user, I want newsletter-style emails to be split into meaningful sections, so one article or callout does not hide another.
4. As a user, I want the system to preserve local context around a matching chunk, so I can relate a returned section to the surrounding part of the message.
5. As a user, I want thread-aware retrieval, so a matched chunk can be related to the thread, sender, and neighboring chunks or messages.
6. As an operator, I want chunk generation to be deterministic, so rehydration and verification produce stable outputs.
7. As an operator, I want chunking to degrade safely when parsing is imperfect, so ingestion continues instead of failing on unusual email bodies.
8. As an operator, I want chunk sizes to remain within embedding model limits with margin, so ingestion does not fail on oversized inputs.
9. As a user, I want signatures, disclaimers, and marketing boilerplate to have low retrieval influence, so search results focus on substantive content.
10. As a user, I want searches for a person, decision, or issue to surface related evidence across messages and threads, so concepts feel connected rather than isolated.

## Functional requirements

### R1. Structure-preserving preprocessing

The system must preserve meaningful structure during chunk preparation, including:

- paragraph boundaries
- list boundaries
- major section separators
- reply and forward boundaries when detectable

It must not reduce the full body into a single whitespace-normalized stream before chunking.

### R2. Section-aware chunking

The system must first segment an email into higher-level sections before applying size-based chunk splitting.

At minimum, the system should distinguish:

- primary authored content
- quoted reply content
- forwarded content
- signatures and footers
- boilerplate or promotional sections when detectable

### R3. Coherent chunk units

Chunks must represent coherent sections rather than arbitrary windows.

Preferred chunk units are:

- one paragraph
- a short group of adjacent paragraphs on the same topic
- one bullet list or list section
- one reply turn or quoted segment

### R4. Token-aware limits

Chunk sizing must be driven by embedding-safe token budgets rather than raw character counts alone.

The system must:

- target a configurable token budget per chunk
- keep a safety margin below the model maximum
- support deterministic fallback splitting for oversized sections

### R5. Minimal, structure-preserving overlap

When overlap is used, it must preserve continuity without blurring unrelated concepts.

Overlap should occur only within the same semantic section and should be configurable.

### R6. Chunk metadata

Each chunk must carry enough metadata to support explanation and context expansion.

Required metadata includes:

- `chunk_index`
- source message ID
- conversation/thread ID
- section type
- section index within the message
- position within the message
- embedding model when present

Desired metadata includes:

- previous and next chunk linkage
- whether the chunk is current authored content or quoted content
- sender/author role where inferable

### R7. Retrieval context expansion

The retrieval layer must be able to expand from a matching chunk into local context.

This means the design must support:

- neighboring chunks in the same message
- message-level context
- thread-level references when appropriate

This requirement is about enabling the behavior through stored metadata and retrieval contracts. It does not require full implementation in the first phase.

### R8. Boilerplate suppression

Low-value content such as signatures, unsubscribe text, tracking fragments, and legal disclaimers should be removed or downgraded before chunk embedding whenever reliably detectable.

If retained, such content must be labeled in metadata so retrieval logic can suppress or deprioritize it.

### R9. Deterministic behavior

Given the same normalized message input and the same configuration, chunk generation must be stable across runs.

This is required for:

- rehydration
- regression testing
- operational verification

### R10. Safe degradation

If the parser cannot confidently classify a section, the system must fall back to a safe generic section type rather than failing ingestion.

If an individual chunk cannot be embedded, the message should still be ingestible.

## Quality requirements

### Q1. Retrieval quality

The redesign should improve precision for concept-level queries over long messages relative to the current chunking approach.

### Q2. Explainability

Operators and users should be able to inspect why a chunk exists and what section of a message it came from.

### Q3. Operational cost control

The number of chunks and embeddings per message should increase only as much as needed to improve retrieval quality.

The design must support tuning of chunking behavior through configuration.

### Q4. Backward compatibility

The system must support rehydrating existing messages into the new chunk format without requiring a new Gmail fetch.

### Q5. Incremental adoption

The design should allow phased rollout:

- better chunk generation first
- richer retrieval use of metadata later

## Acceptance criteria

The redesign should be considered ready for implementation when the proposed design can satisfy the following:

1. A message with multiple topical paragraphs is split into coherent paragraph-group chunks rather than one large body chunk.
2. A reply email with quoted history stores current authored text separately from quoted text.
3. A newsletter-style email produces multiple topical chunks instead of one dominant mixed chunk.
4. A chunk record can be traced back to its message, thread, section type, and neighboring chunk positions.
5. Oversized sections are split deterministically using semantic boundaries before any hard fallback.
6. Rehydration of stored raw Gmail payloads can regenerate the new chunk set.
7. Failed embeddings do not block message ingestion.

## Open questions

These questions should be resolved in design:

1. How much section classification do we need in the first iteration versus later refinement?
2. What token budget should be the default for the current embedding model?
3. Should signatures and footers be dropped entirely or stored with suppressible metadata?
4. How much retrieval logic should change in the first implementation phase versus a follow-up phase?
