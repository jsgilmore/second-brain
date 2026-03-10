"""Section-aware, token-aware email chunking pipeline.

Implements the 6-stage pipeline from specs/email-chunking/design.md:
1. Normalize and preserve structure
2. Segment the message into email-aware sections
3. Build coherent chunk candidates from those sections
4. Split oversized candidates using token-aware rules
5. Attach structural metadata
6. Embed the final chunks
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from typing import Optional

from second_brain_service.common.config import (
    CHUNK_MAX_TOKENS,
    CHUNK_OVERLAP_TOKENS,
    CHUNK_TARGET_TOKENS,
)


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

# Approximate tokens using word-count heuristic (~0.75 tokens per word for
# English text).  This avoids a hard dependency on tiktoken or a model-specific
# tokenizer while staying conservative enough for embedding-model limits.
_WORD_SPLIT_RE = re.compile(r"\S+")


def estimate_tokens(text: str) -> int:
    """Return a conservative token estimate for *text*."""
    if not text:
        return 0
    words = _WORD_SPLIT_RE.findall(text)
    # ~1.33 tokens per whitespace-delimited word is a safe upper-bound for
    # English text with the cl100k / o200k family of tokenizers.
    return max(1, int(len(words) * 1.33 + 0.5))


# ---------------------------------------------------------------------------
# Section types and data model
# ---------------------------------------------------------------------------

SECTION_TYPES = frozenset(
    {"body", "quote", "forward", "signature", "footer", "boilerplate", "unknown"}
)

SOURCE_ROLES = frozenset({"current_author", "quoted_author", "unknown"})


@dataclass
class Section:
    section_index: int
    section_type: str  # one of SECTION_TYPES
    text: str
    source_role: str = "unknown"  # one of SOURCE_ROLES
    attributes: dict = field(default_factory=dict)


@dataclass
class Chunk:
    chunk_index: int
    text: str
    metadata: dict = field(default_factory=dict)


@dataclass
class ChunkingDiagnostics:
    section_count: int = 0
    unknown_section_count: int = 0
    oversized_candidate_count: int = 0
    sentence_split_count: int = 0
    word_fallback_count: int = 0


# ---------------------------------------------------------------------------
# Section detection patterns
# ---------------------------------------------------------------------------

# "On <date>, <name> wrote:" style reply headers
_REPLY_HEADER_RE = re.compile(
    r"^On\s+.{6,80}\s+wrote:\s*$", re.IGNORECASE
)

# Outlook-style reply separator
_OUTLOOK_SEPARATOR_RE = re.compile(
    r"^-{2,}\s*(?:Original\s+Message|Forwarded\s+message)\s*-{2,}\s*$",
    re.IGNORECASE,
)

# ">" prefix quoting
_QUOTE_PREFIX_RE = re.compile(r"^>{1,3}\s?")

# Forwarded-message header
_FORWARD_HEADER_RE = re.compile(
    r"^-{2,}\s*Forwarded\s+message\s*-{2,}\s*$", re.IGNORECASE
)

# Begin Forwarded Message (Apple Mail)
_APPLE_FORWARD_RE = re.compile(
    r"^Begin\s+forwarded\s+message:\s*$", re.IGNORECASE
)

# Signature separator: line that is exactly "-- " or "--"
_SIGNATURE_SEP_RE = re.compile(r"^--\s{0,2}$")

# Common footer / unsubscribe / disclaimer patterns
_FOOTER_RE = re.compile(
    r"(?:unsubscribe|opt[- ]?out|manage\s+(?:preferences|subscription)|"
    r"view\s+(?:in|online|browser)|privacy\s+policy|terms\s+(?:of\s+(?:service|use)|and\s+conditions)|"
    r"copyright\s+\d{4}|all\s+rights\s+reserved|"
    r"this\s+(?:email|message)\s+(?:was\s+sent|is\s+intended)|"
    r"confidential(?:ity)?\s+(?:notice|disclaimer)|"
    r"if\s+you\s+(?:no\s+longer|don.t)\s+(?:wish|want)\s+to\s+receive)",
    re.IGNORECASE,
)

# Forwarded message header fields (From:, Date:, Subject:, To:)
_FWD_FIELD_RE = re.compile(
    r"^(?:From|Date|Subject|To|Cc|Sent|Received):\s+", re.IGNORECASE
)

# Sentence-boundary split (used for oversized chunk splitting)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


# ---------------------------------------------------------------------------
# Stage 1: Structure-preserving normalization
# ---------------------------------------------------------------------------

def _normalize_preserve_structure(text: str) -> str:
    """Clean text while preserving paragraph and section boundaries."""
    if not text:
        return ""
    # Replace special whitespace chars but keep newlines
    normalized = (
        text.replace("\u00a0", " ")
        .replace("\u200b", "")
        .replace("\u200c", "")
        .replace("\u200d", "")
        .replace("\ufeff", "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    # Normalize each line individually: strip trailing whitespace, collapse
    # internal runs of spaces/tabs (but preserve the line itself).
    lines = []
    for line in normalized.split("\n"):
        cleaned = re.sub(r"[ \t]+", " ", line).strip()
        lines.append(cleaned)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Stage 2: Section detection
# ---------------------------------------------------------------------------

def _detect_sections(text: str, diagnostics: Optional[ChunkingDiagnostics] = None) -> list[Section]:
    """Segment *text* into a list of :class:`Section` objects.

    Uses deterministic heuristics; uncertain regions get type ``"unknown"``.
    """
    if not text:
        return []

    lines = text.split("\n")
    raw_segments: list[dict] = []
    current: dict = {"type": "body", "role": "current_author", "lines": []}

    i = 0
    while i < len(lines):
        line = lines[i]

        # --- Forwarded message block --------------------------------
        if _FORWARD_HEADER_RE.match(line) or _APPLE_FORWARD_RE.match(line):
            if current["lines"]:
                raw_segments.append(current)
            current = {"type": "forward", "role": "quoted_author", "lines": [line]}
            i += 1
            continue

        # --- Outlook-style separator (reply or forward) ---------------
        if _OUTLOOK_SEPARATOR_RE.match(line):
            sep_lower = line.lower()
            if current["lines"]:
                raw_segments.append(current)
            if "forward" in sep_lower:
                current = {"type": "forward", "role": "quoted_author", "lines": [line]}
            else:
                current = {"type": "quote", "role": "quoted_author", "lines": [line]}
            i += 1
            continue

        # --- Reply header ("On ... wrote:") ---------------------------
        if _REPLY_HEADER_RE.match(line):
            if current["lines"]:
                raw_segments.append(current)
            current = {"type": "quote", "role": "quoted_author", "lines": [line]}
            i += 1
            continue

        # --- ">" prefix quoting ----------------------------------------
        if _QUOTE_PREFIX_RE.match(line):
            if current["type"] != "quote":
                if current["lines"]:
                    raw_segments.append(current)
                current = {"type": "quote", "role": "quoted_author", "lines": []}
            # Strip the leading ">" for cleaner chunk text
            current["lines"].append(_QUOTE_PREFIX_RE.sub("", line))
            i += 1
            continue

        # --- Signature separator ----------------------------------------
        if _SIGNATURE_SEP_RE.match(line):
            if current["lines"]:
                raw_segments.append(current)
            current = {"type": "signature", "role": "current_author", "lines": []}
            i += 1
            continue

        # --- Footer / boilerplate detection ----------------------------
        if _FOOTER_RE.search(line):
            if current["type"] not in ("footer", "boilerplate"):
                if current["lines"]:
                    raw_segments.append(current)
                current = {"type": "footer", "role": "unknown", "lines": []}
            current["lines"].append(line)
            i += 1
            continue

        # --- Default: continue current section -------------------------
        # Quotes usually end once the ">"-prefixed or reply-header block ends,
        # but forwarded content should remain a forwarded section until an
        # explicit new boundary is detected.
        if (
            current["type"] == "quote"
            and line.strip()
            and not _FWD_FIELD_RE.match(line)
            and not _QUOTE_PREFIX_RE.match(line)
        ):
            if current["lines"]:
                raw_segments.append(current)
            current = {"type": "body", "role": "current_author", "lines": []}

        current["lines"].append(line)
        i += 1

    if current["lines"]:
        raw_segments.append(current)

    # Build Section objects, dropping completely empty segments
    sections: list[Section] = []
    for idx, seg in enumerate(raw_segments):
        text_block = "\n".join(seg["lines"]).strip()
        if not text_block:
            continue
        sections.append(
            Section(
                section_index=len(sections),
                section_type=seg["type"],
                text=text_block,
                source_role=seg["role"],
            )
        )

    if not sections:
        sections.append(
            Section(
                section_index=0,
                section_type="unknown",
                text=text.strip(),
                source_role="unknown",
            )
        )
    if diagnostics is not None:
        diagnostics.section_count = len(sections)
        diagnostics.unknown_section_count = sum(1 for section in sections if section.section_type == "unknown")
    return sections


# ---------------------------------------------------------------------------
# Stage 3 & 4: Build chunk candidates and token-aware splitting
# ---------------------------------------------------------------------------

def _split_into_paragraphs(text: str) -> list[str]:
    """Split text on blank-line boundaries into paragraph groups."""
    paragraphs: list[str] = []
    current_lines: list[str] = []
    for line in text.split("\n"):
        if not line.strip():
            if current_lines:
                paragraphs.append("\n".join(current_lines))
                current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        paragraphs.append("\n".join(current_lines))
    return paragraphs


def _split_oversized(
    text: str,
    max_tokens: int,
    diagnostics: Optional[ChunkingDiagnostics] = None,
) -> list[str]:
    """Split a single oversized text block into pieces that fit *max_tokens*.

    Tries sentence boundaries first, then falls back to word-level splitting.
    """
    if estimate_tokens(text) <= max_tokens:
        return [text]
    if diagnostics is not None:
        diagnostics.oversized_candidate_count += 1

    # Try sentence-level splitting
    sentences = _SENTENCE_SPLIT_RE.split(text)
    if len(sentences) > 1:
        if diagnostics is not None:
            diagnostics.sentence_split_count += 1
        pieces: list[str] = []
        current = ""
        for sentence in sentences:
            candidate = f"{current} {sentence}".strip() if current else sentence
            if estimate_tokens(candidate) <= max_tokens:
                current = candidate
            else:
                if current:
                    pieces.append(current)
                # If a single sentence exceeds max_tokens, force-split on words
                if estimate_tokens(sentence) > max_tokens:
                    pieces.extend(_force_split_words(sentence, max_tokens, diagnostics=diagnostics))
                    current = ""
                else:
                    current = sentence
        if current:
            pieces.append(current)
        return pieces

    # Single block with no sentence boundaries – force-split on words
    return _force_split_words(text, max_tokens, diagnostics=diagnostics)


def _force_split_words(
    text: str,
    max_tokens: int,
    diagnostics: Optional[ChunkingDiagnostics] = None,
) -> list[str]:
    """Last-resort: split on word boundaries to stay within *max_tokens*."""
    if diagnostics is not None:
        diagnostics.word_fallback_count += 1
    words = text.split()
    pieces: list[str] = []
    current_words: list[str] = []
    for word in words:
        current_words.append(word)
        if estimate_tokens(" ".join(current_words)) > max_tokens:
            if len(current_words) > 1:
                current_words.pop()
                pieces.append(" ".join(current_words))
                current_words = [word]
            else:
                # Single word exceeds limit – include it anyway
                pieces.append(word)
                current_words = []
    if current_words:
        pieces.append(" ".join(current_words))
    return pieces


def _build_section_chunks(
    section: Section,
    *,
    target_tokens: int,
    max_tokens: int,
    overlap_tokens: int,
    diagnostics: Optional[ChunkingDiagnostics] = None,
) -> list[str]:
    """Build chunk texts from a single section.

    Groups paragraphs up to *target_tokens*, splits oversized paragraphs,
    and applies section-local overlap.
    """
    paragraphs = _split_into_paragraphs(section.text)
    if not paragraphs:
        return []

    # Phase A: group paragraphs into candidates within target_tokens
    candidates: list[str] = []
    current_parts: list[str] = []
    current_tokens = 0
    for para in paragraphs:
        para_tokens = estimate_tokens(para)
        if current_parts and (current_tokens + para_tokens) > target_tokens:
            candidates.append("\n\n".join(current_parts))
            current_parts = []
            current_tokens = 0
        current_parts.append(para)
        current_tokens += para_tokens
    if current_parts:
        candidates.append("\n\n".join(current_parts))

    # Phase B: split any oversized candidate
    split_candidates: list[str] = []
    for candidate in candidates:
        if estimate_tokens(candidate) > max_tokens:
            split_candidates.extend(_split_oversized(candidate, max_tokens, diagnostics=diagnostics))
        else:
            split_candidates.append(candidate)

    # Phase C: apply section-local overlap
    if overlap_tokens <= 0 or len(split_candidates) <= 1:
        return split_candidates

    final: list[str] = [split_candidates[0]]
    for i in range(1, len(split_candidates)):
        prev_text = split_candidates[i - 1]
        overlap_prefix = _extract_overlap_suffix(prev_text, overlap_tokens)
        if overlap_prefix:
            merged = f"{overlap_prefix}\n\n{split_candidates[i]}"
            # Only add overlap if it stays within max
            if estimate_tokens(merged) <= max_tokens:
                final.append(merged)
            else:
                final.append(split_candidates[i])
        else:
            final.append(split_candidates[i])
    return final


def _extract_overlap_suffix(text: str, target_tokens: int) -> str:
    """Return the trailing portion of *text* that fits within *target_tokens*."""
    words = text.split()
    if not words:
        return ""
    # Walk backwards to find how many trailing words fit
    suffix_words: list[str] = []
    for word in reversed(words):
        trial = [word] + suffix_words
        if estimate_tokens(" ".join(trial)) > target_tokens:
            break
        suffix_words.insert(0, word)
    return " ".join(suffix_words)


# ---------------------------------------------------------------------------
# Boilerplate suppression policy
# ---------------------------------------------------------------------------

_SUPPRESSED_SECTION_TYPES = frozenset({"signature", "footer", "boilerplate"})


def _should_suppress(section: Section) -> bool:
    """Return True if the section should be marked as suppressed."""
    return section.section_type in _SUPPRESSED_SECTION_TYPES


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def prepare_message_sections(
    subject: Optional[str],
    body_text: str,
    body_html: Optional[str] = None,
    headers: Optional[dict] = None,
    *,
    diagnostics: Optional[ChunkingDiagnostics] = None,
) -> list[Section]:
    """Normalize text and return a list of detected sections.

    *body_html* and *headers* are accepted for future use but currently
    the pipeline operates on the already-extracted plain text.
    """
    normalized = _normalize_preserve_structure(body_text)
    return _detect_sections(normalized, diagnostics=diagnostics)


def build_chunks(
    subject: Optional[str],
    body_text: str,
    body_html: Optional[str] = None,
    headers: Optional[dict] = None,
    *,
    target_tokens: int = CHUNK_TARGET_TOKENS,
    max_tokens: int = CHUNK_MAX_TOKENS,
    overlap_tokens: int = CHUNK_OVERLAP_TOKENS,
    diagnostics: Optional[ChunkingDiagnostics] = None,
) -> list[Chunk]:
    """Run the full chunking pipeline and return :class:`Chunk` objects.

    This is the primary entry point called by ingestion code.
    """
    sections = prepare_message_sections(subject, body_text, body_html, headers, diagnostics=diagnostics)

    chunks: list[Chunk] = []
    chunk_index = 0

    subject_prefix = f"Subject: {subject}\n\n" if subject else ""

    for section in sections:
        suppressed = _should_suppress(section)

        chunk_texts = _build_section_chunks(
            section,
            target_tokens=target_tokens,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
            diagnostics=diagnostics,
        )

        for pos, text in enumerate(chunk_texts):
            # Add subject prefix to the very first chunk only
            final_text = f"{subject_prefix}{text}" if chunk_index == 0 and subject_prefix else text

            chunk = Chunk(
                chunk_index=chunk_index,
                text=final_text,
                metadata={
                    "section_type": section.section_type,
                    "section_index": section.section_index,
                    "position_start": pos,
                    "position_end": pos,
                    "source_role": section.source_role,
                    "is_quote": section.section_type in ("quote", "forward"),
                    "suppressed": suppressed,
                    "prev_chunk_index": chunk_index - 1 if chunk_index > 0 else None,
                    "next_chunk_index": None,  # filled in below
                },
            )
            chunks.append(chunk)
            chunk_index += 1

    # Fill in next_chunk_index linkage
    for i in range(len(chunks) - 1):
        chunks[i].metadata["next_chunk_index"] = chunks[i + 1].chunk_index

    return chunks


def build_message_chunks(
    subject: Optional[str],
    body_text: str,
    embedding_client,
    body_html: Optional[str] = None,
    headers: Optional[dict] = None,
) -> list[dict]:
    """Build chunk dicts ready for storage and embedding.

    Drop-in replacement for :func:`embeddings.build_message_chunks`.
    """
    diagnostics = ChunkingDiagnostics()
    pipeline_chunks = build_chunks(
        subject, body_text, body_html, headers, diagnostics=diagnostics,
    )

    if not pipeline_chunks:
        return []

    # Separate embeddable vs suppressed chunks
    embeddable_indices: list[int] = []
    embeddable_texts: list[str] = []
    for i, chunk in enumerate(pipeline_chunks):
        if not chunk.metadata.get("suppressed"):
            embeddable_indices.append(i)
            embeddable_texts.append(chunk.text)

    # Embed non-suppressed chunks
    embeddings: list = []
    if embeddable_texts and embedding_client.enabled:
        try:
            embeddings = embedding_client.embed_texts(embeddable_texts)
        except Exception as exc:
            print(
                f"warning: batch embedding failed for message chunks: {exc}",
                file=sys.stderr,
                flush=True,
            )
            embeddings = [None] * len(embeddable_texts)
    else:
        embeddings = [None] * len(embeddable_texts)

    # Build final chunk dicts
    result: list[dict] = []
    embed_idx = 0
    embedding_failures_by_section: dict[str, int] = {}
    for chunk in pipeline_chunks:
        chunk_dict: dict = {
            "chunk_index": chunk.chunk_index,
            "text": chunk.text,
            "metadata": chunk.metadata,
        }
        if not chunk.metadata.get("suppressed") and embed_idx < len(embeddings):
            emb = embeddings[embed_idx]
            if emb is not None:
                chunk_dict["embedding_model"] = embedding_client.model
                chunk_dict["embedding"] = emb
            else:
                section_type = str(chunk.metadata.get("section_type", "unknown"))
                embedding_failures_by_section[section_type] = embedding_failures_by_section.get(section_type, 0) + 1
            embed_idx += 1
        result.append(chunk_dict)

    _log_chunk_summary(pipeline_chunks, diagnostics, embedding_failures_by_section)
    return result


def _log_chunk_summary(
    chunks: list[Chunk],
    diagnostics: ChunkingDiagnostics,
    embedding_failures_by_section: dict[str, int],
) -> None:
    """Print a short diagnostic summary to stderr."""
    total = len(chunks)
    suppressed = sum(1 for c in chunks if c.metadata.get("suppressed"))
    section_types: dict[str, int] = {}
    for c in chunks:
        st = c.metadata.get("section_type", "unknown")
        section_types[st] = section_types.get(st, 0) + 1
    parts = [
        f"sections={diagnostics.section_count}",
        f"unknown_sections={diagnostics.unknown_section_count}",
        f"chunks={total}",
        f"suppressed={suppressed}",
        f"oversized={diagnostics.oversized_candidate_count}",
        f"sentence_splits={diagnostics.sentence_split_count}",
        f"word_fallbacks={diagnostics.word_fallback_count}",
    ]
    for st, count in sorted(section_types.items()):
        parts.append(f"{st}={count}")
    if embedding_failures_by_section:
        failure_parts = ",".join(
            f"{section_type}:{count}"
            for section_type, count in sorted(embedding_failures_by_section.items())
        )
        parts.append(f"embedding_failures={failure_parts}")
    print(f"chunking: {' '.join(parts)}", file=sys.stderr, flush=True)
