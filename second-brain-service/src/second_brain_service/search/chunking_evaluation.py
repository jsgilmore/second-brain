from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from second_brain_service.search.chunking import build_chunks, estimate_tokens
from second_brain_service.search.embeddings import chunk_text
from second_brain_service.search.validation_corpus import VALIDATION_CORPUS, ValidationCase, ValidationQuery


_TERM_RE = re.compile(r"[A-Za-z0-9']{3,}")


def _tokenize(value: str) -> list[str]:
    return [token.lower() for token in _TERM_RE.findall(value or "")]


def _legacy_chunks(case: ValidationCase) -> list[dict[str, Any]]:
    prefix = f"Subject: {case.subject}\n\n" if case.subject else ""
    texts = chunk_text(f"{prefix}{case.body_text}".strip())
    return [{"text": text, "suppressed": False, "section_type": "body"} for text in texts]


def _section_aware_chunks(case: ValidationCase) -> list[dict[str, Any]]:
    return [
        {
            "text": chunk.text,
            "suppressed": bool(chunk.metadata.get("suppressed")),
            "section_type": chunk.metadata.get("section_type", "unknown"),
        }
        for chunk in build_chunks(case.subject, case.body_text)
    ]


def _score_chunk(query: str, chunk: dict[str, Any]) -> tuple[int, int]:
    text = chunk["text"].lower()
    overlap = sum(text.count(token) for token in _tokenize(query))
    return overlap, -estimate_tokens(chunk["text"])


def _top_match(query: str, chunks: list[dict[str, Any]], *, skip_suppressed: bool) -> dict[str, Any] | None:
    scored: list[tuple[tuple[int, int], dict[str, Any]]] = []
    for chunk in chunks:
        if skip_suppressed and chunk.get("suppressed"):
            continue
        score = _score_chunk(query, chunk)
        if score[0] <= 0:
            continue
        scored.append((score, chunk))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def evaluate_chunking_corpus() -> dict[str, Any]:
    query_rows: list[dict[str, Any]] = []
    legacy_chunk_counts: list[int] = []
    section_chunk_counts: list[int] = []
    legacy_token_sizes: list[int] = []
    section_token_sizes: list[int] = []
    legacy_hits = 0
    section_hits = 0
    total_queries = 0
    suppressed_chunk_total = 0

    for case in VALIDATION_CORPUS:
        legacy_chunks = _legacy_chunks(case)
        section_chunks = _section_aware_chunks(case)
        legacy_chunk_counts.append(len(legacy_chunks))
        section_chunk_counts.append(len(section_chunks))
        suppressed_chunk_total += sum(1 for chunk in section_chunks if chunk["suppressed"])

        for query in case.queries:
            total_queries += 1
            legacy_top = _top_match(query.query, legacy_chunks, skip_suppressed=False)
            section_top = _top_match(query.query, section_chunks, skip_suppressed=True)
            legacy_hit = bool(legacy_top and query.expected_excerpt.lower() in legacy_top["text"].lower())
            section_hit = bool(section_top and query.expected_excerpt.lower() in section_top["text"].lower())
            legacy_hits += int(legacy_hit)
            section_hits += int(section_hit)
            legacy_tokens = estimate_tokens(legacy_top["text"]) if legacy_top else 0
            section_tokens = estimate_tokens(section_top["text"]) if section_top else 0
            if legacy_tokens:
                legacy_token_sizes.append(legacy_tokens)
            if section_tokens:
                section_token_sizes.append(section_tokens)
            query_rows.append(
                {
                    "case_id": case.case_id,
                    "category": case.category,
                    "query": query.query,
                    "expected_excerpt": query.expected_excerpt,
                    "legacy_hit": legacy_hit,
                    "section_hit": section_hit,
                    "legacy_tokens": legacy_tokens,
                    "section_tokens": section_tokens,
                    "legacy_chunk_preview": legacy_top["text"][:120] if legacy_top else "",
                    "section_chunk_preview": section_top["text"][:120] if section_top else "",
                }
            )

    def _avg(values: list[int]) -> float:
        return round(sum(values) / len(values), 2) if values else 0.0

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases": len(VALIDATION_CORPUS),
        "queries": total_queries,
        "suppressed_chunks": suppressed_chunk_total,
        "legacy": {
            "top1_hits": legacy_hits,
            "top1_hit_rate": round(legacy_hits / total_queries, 2) if total_queries else 0.0,
            "avg_chunks_per_message": _avg(legacy_chunk_counts),
            "avg_top_hit_tokens": _avg(legacy_token_sizes),
        },
        "section_aware": {
            "top1_hits": section_hits,
            "top1_hit_rate": round(section_hits / total_queries, 2) if total_queries else 0.0,
            "avg_chunks_per_message": _avg(section_chunk_counts),
            "avg_top_hit_tokens": _avg(section_token_sizes),
        },
        "query_rows": query_rows,
    }


def render_chunking_evaluation_markdown(results: dict[str, Any]) -> str:
    lines = [
        "# Email Chunking Evaluation",
        "",
        f"Generated: {results['generated_at']}",
        "",
        f"Corpus: {results['cases']} synthetic messages, {results['queries']} representative queries.",
        "",
        "## Summary",
        "",
        "| metric | legacy chunking | section-aware chunking |",
        "| --- | ---: | ---: |",
        f"| top-1 query hits | {results['legacy']['top1_hits']} | {results['section_aware']['top1_hits']} |",
        f"| top-1 hit rate | {results['legacy']['top1_hit_rate']:.2f} | {results['section_aware']['top1_hit_rate']:.2f} |",
        f"| avg chunks per message | {results['legacy']['avg_chunks_per_message']:.2f} | {results['section_aware']['avg_chunks_per_message']:.2f} |",
        f"| avg top-hit chunk tokens | {results['legacy']['avg_top_hit_tokens']:.2f} | {results['section_aware']['avg_top_hit_tokens']:.2f} |",
        f"| suppressed chunks in section-aware corpus | n/a | {results['suppressed_chunks']} |",
        "",
        "## Query Results",
        "",
        "| case | query | legacy hit | section-aware hit | legacy tokens | section-aware tokens |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in results["query_rows"]:
        lines.append(
            f"| {row['case_id']} | {row['query']} | "
            f"{'yes' if row['legacy_hit'] else 'no'} | {'yes' if row['section_hit'] else 'no'} | "
            f"{row['legacy_tokens']} | {row['section_tokens']} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- The synthetic corpus covers short mail, long multi-topic mail, reply chains, forwarded threads, and newsletter-style mail.",
            "- Both chunkers should still find the relevant evidence on these representative queries, but the section-aware chunker is expected to return smaller and more focused chunks.",
            "- The section-aware pipeline also suppresses signature/footer chunks, reducing retrieval pressure from low-value content.",
        ]
    )
    return "\n".join(lines) + "\n"
