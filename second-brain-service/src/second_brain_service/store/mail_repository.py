from collections import Counter
import re
import sys
import time
from typing import Any, Optional

from psycopg import errors as psycopg_errors
from psycopg.types.json import Jsonb

from second_brain_service.common.config import ACTIVE_EMBEDDING_MODEL, PUBLIC_BASE_URL
from second_brain_service.common.sanitize import sanitize_jsonish, sanitize_text
from second_brain_service.store.connection import iso_to_datetime, utc_now, with_connection


TERM_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'._-]{2,}")
SUBJECT_PREFIX_RE = re.compile(r"^(?:(?:re|fw|fwd)\s*:\s*)+", re.IGNORECASE)
TERM_STOPWORDS = {
    "able",
    "about",
    "across",
    "after",
    "again",
    "against",
    "almost",
    "along",
    "already",
    "also",
    "among",
    "another",
    "anyone",
    "anything",
    "around",
    "because",
    "been",
    "before",
    "being",
    "below",
    "both",
    "came",
    "come",
    "comes",
    "complete",
    "could",
    "each",
    "email",
    "every",
    "first",
    "from",
    "have",
    "here",
    "into",
    "just",
    "keep",
    "mail",
    "made",
    "many",
    "message",
    "messages",
    "more",
    "most",
    "much",
    "need",
    "other",
    "over",
    "part",
    "please",
    "really",
    "received",
    "review",
    "same",
    "several",
    "settings",
    "should",
    "some",
    "such",
    "team",
    "than",
    "that",
    "thank",
    "thanks",
    "the",
    "their",
    "them",
    "there",
    "these",
    "they",
    "this",
    "thread",
    "threads",
    "through",
    "under",
    "using",
    "used",
    "user",
    "users",
    "very",
    "what",
    "when",
    "where",
    "which",
    "while",
    "with",
    "would",
    "you",
    "your",
    "and",
    "application",
    "account",
    "accounts",
    "data",
    "documentation",
    "for",
    "our",
    "platform",
    "service",
    "services",
    "were",
    "will",
}


def build_message_url(message_row: dict[str, Any]) -> str:
    public_url = (
        message_row.get("metadata", {}).get("public_url")
        if isinstance(message_row.get("metadata"), dict)
        else None
    )
    if PUBLIC_BASE_URL and message_row.get("id"):
        return f"{PUBLIC_BASE_URL}/messages/{message_row['id']}"
    if public_url:
        return public_url

    external_id = message_row.get("external_id")
    source = message_row.get("source")
    if source == "gmail" and external_id:
        return f"https://mail.google.com/mail/u/0/#all/{external_id}"
    return f"message://{source}/{external_id}"


def _normalize_subject(subject: Optional[str]) -> str:
    if not subject:
        return "(no subject)"
    cleaned = subject.strip()
    while True:
        updated = SUBJECT_PREFIX_RE.sub("", cleaned).strip()
        if updated == cleaned:
            return cleaned or "(no subject)"
        cleaned = updated


def _extract_terms(text: str) -> list[str]:
    terms = []
    for token in TERM_TOKEN_RE.findall((text or "").lower()):
        if token in TERM_STOPWORDS or token.isdigit():
            continue
        if "@" in token:
            continue
        terms.append(token)
    return terms


def _fetch_health_counts(cur) -> dict[str, Any]:
    cur.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM contacts) AS contacts,
          (SELECT COUNT(*) FROM conversations) AS conversations,
          (SELECT COUNT(*) FROM messages) AS messages,
          (SELECT COUNT(*) FROM message_participants) AS message_participants,
          (SELECT COUNT(*) FROM message_chunks) AS message_chunks,
          (SELECT COUNT(*) FROM sync_state) AS sync_state
        """
    )
    return cur.fetchone()


def _upsert_contact(cur, source: str, contact: dict[str, Any]) -> Optional[str]:
    external_id = contact.get("external_id")
    if not external_id:
        return None

    cur.execute(
        """
        INSERT INTO contacts (source, external_id, display_name, email, phone, metadata)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (source, external_id)
        DO UPDATE SET
          display_name = COALESCE(EXCLUDED.display_name, contacts.display_name),
          email = COALESCE(EXCLUDED.email, contacts.email),
          phone = COALESCE(EXCLUDED.phone, contacts.phone),
          metadata = contacts.metadata || EXCLUDED.metadata
        RETURNING id
        """,
        (
            source,
            external_id,
            contact.get("display_name"),
            contact.get("email"),
            contact.get("phone"),
            Jsonb(contact.get("metadata", {})),
        ),
    )
    row = cur.fetchone()
    return str(row["id"]) if row else None


def _merge_contact_seed(existing: Optional[dict[str, Any]], candidate: dict[str, Any]) -> dict[str, Any]:
    if not existing:
        return {
            "external_id": candidate.get("external_id"),
            "display_name": candidate.get("display_name"),
            "email": candidate.get("email"),
            "phone": candidate.get("phone"),
            "metadata": dict(candidate.get("metadata", {})),
        }

    merged = dict(existing)
    if not merged.get("display_name") and candidate.get("display_name"):
        merged["display_name"] = candidate.get("display_name")
    if not merged.get("email") and candidate.get("email"):
        merged["email"] = candidate.get("email")
    if not merged.get("phone") and candidate.get("phone"):
        merged["phone"] = candidate.get("phone")
    merged["metadata"] = {
        **(candidate.get("metadata", {}) or {}),
        **(merged.get("metadata", {}) or {}),
    }
    return merged


def _upsert_contacts_for_message(
    cur,
    source: str,
    sender: dict[str, Any],
    participants: list[dict[str, Any]],
) -> dict[str, str]:
    contact_seeds: dict[str, dict[str, Any]] = {}

    sender_external_id = sender.get("external_id")
    if sender_external_id:
        contact_seeds[sender_external_id] = _merge_contact_seed(contact_seeds.get(sender_external_id), sender)

    for participant in participants:
        participant_external_id = participant.get("external_id")
        if not participant_external_id:
            continue
        contact_seeds[participant_external_id] = _merge_contact_seed(
            contact_seeds.get(participant_external_id),
            participant,
        )

    contact_ids: dict[str, str] = {}
    for external_id in sorted(contact_seeds):
        contact_id = _upsert_contact(cur, source, contact_seeds[external_id])
        if contact_id:
            contact_ids[external_id] = contact_id
    return contact_ids


def _load_message_participants(cur, message_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not message_ids:
        return {}

    cur.execute(
        """
        SELECT
          mp.message_id,
          mp.participant_type,
          mp.position,
          mp.header_value,
          mp.display_name,
          mp.email,
          mp.metadata,
          mp.contact_id
        FROM message_participants mp
        WHERE mp.message_id = ANY(%s::uuid[])
        ORDER BY
          mp.message_id,
          CASE mp.participant_type
            WHEN 'from' THEN 0
            WHEN 'reply_to' THEN 1
            WHEN 'to' THEN 2
            WHEN 'cc' THEN 3
            WHEN 'bcc' THEN 4
            ELSE 5
          END,
          mp.position ASC
        """,
        (message_ids,),
    )

    participants_by_message: dict[str, list[dict[str, Any]]] = {}
    for row in cur.fetchall():
        message_id = str(row["message_id"])
        participant = {
            "type": row["participant_type"],
            "position": row["position"],
            "header_value": row["header_value"],
            "display_name": row["display_name"],
            "email": row["email"],
            "metadata": row.get("metadata") or {},
        }
        if row.get("contact_id"):
            participant["contact_id"] = str(row["contact_id"])
        participants_by_message.setdefault(message_id, []).append(participant)
    return participants_by_message


def _upsert_message_record(cur, payload: dict[str, Any], embedding_dimension: int) -> dict[str, Any]:
    source = payload["source"]
    external_id = sanitize_text(payload["external_id"])
    conversation_external_id = sanitize_text(payload["conversation_external_id"])
    conversation_title = sanitize_text(payload.get("conversation_title"))
    conversation_metadata = sanitize_jsonish(payload.get("conversation_metadata", {}))
    sent_at = iso_to_datetime(payload["sent_at"])
    body_text = sanitize_text(payload.get("body_text", ""))
    body_html = sanitize_text(payload.get("body_html")) if payload.get("body_html") else None
    subject = sanitize_text(payload.get("subject"))
    raw_payload = sanitize_jsonish(payload.get("raw_payload", {}))
    metadata = sanitize_jsonish(payload.get("metadata", {}))
    sender = sanitize_jsonish(payload.get("sender", {}))
    participants = sanitize_jsonish(payload.get("participants", []))
    attachments = sanitize_jsonish(payload.get("attachments"))
    chunks = sanitize_jsonish(payload.get("chunks"))
    reply_to = sanitize_text(payload.get("reply_to"))
    message_id_header = sanitize_text(payload.get("message_id_header"))
    in_reply_to = sanitize_text(payload.get("in_reply_to"))
    references_header = sanitize_text(payload.get("references_header"))
    list_id = sanitize_text(payload.get("list_id"))
    delivered_to = sanitize_text(payload.get("delivered_to"))

    contact_ids = _upsert_contacts_for_message(cur, source, sender, participants)
    sender_contact_id = contact_ids.get(sender.get("external_id"))

    cur.execute(
        """
        INSERT INTO conversations (source, external_id, title, is_group, metadata, first_message_at, last_message_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source, external_id)
        DO UPDATE SET
          title = COALESCE(EXCLUDED.title, conversations.title),
          is_group = EXCLUDED.is_group,
          metadata = conversations.metadata || EXCLUDED.metadata,
          first_message_at = COALESCE(
            LEAST(conversations.first_message_at, EXCLUDED.first_message_at),
            conversations.first_message_at,
            EXCLUDED.first_message_at
          ),
          last_message_at = COALESCE(
            GREATEST(conversations.last_message_at, EXCLUDED.last_message_at),
            conversations.last_message_at,
            EXCLUDED.last_message_at
          )
        RETURNING id
        """,
        (
            source,
            conversation_external_id,
            conversation_title,
            payload.get("is_group", False),
            Jsonb(conversation_metadata),
            sent_at,
            sent_at,
        ),
    )
    conversation_id = cur.fetchone()["id"]

    cur.execute(
        """
        INSERT INTO messages (
          source,
          external_id,
          conversation_id,
          sender_contact_id,
          subject,
          body_text,
          body_html,
          reply_to,
          message_id_header,
          in_reply_to,
          references_header,
          list_id,
          delivered_to,
          sent_at,
          raw_payload,
          metadata
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source, external_id)
        DO UPDATE SET
          conversation_id = EXCLUDED.conversation_id,
          sender_contact_id = COALESCE(EXCLUDED.sender_contact_id, messages.sender_contact_id),
          subject = COALESCE(EXCLUDED.subject, messages.subject),
          body_text = EXCLUDED.body_text,
          body_html = COALESCE(EXCLUDED.body_html, messages.body_html),
          reply_to = COALESCE(EXCLUDED.reply_to, messages.reply_to),
          message_id_header = COALESCE(EXCLUDED.message_id_header, messages.message_id_header),
          in_reply_to = COALESCE(EXCLUDED.in_reply_to, messages.in_reply_to),
          references_header = COALESCE(EXCLUDED.references_header, messages.references_header),
          list_id = COALESCE(EXCLUDED.list_id, messages.list_id),
          delivered_to = COALESCE(EXCLUDED.delivered_to, messages.delivered_to),
          sent_at = EXCLUDED.sent_at,
          raw_payload = EXCLUDED.raw_payload,
          metadata = messages.metadata || EXCLUDED.metadata
        RETURNING id
        """,
        (
            source,
            external_id,
            conversation_id,
            sender_contact_id,
            subject,
            body_text,
            body_html,
            reply_to,
            message_id_header,
            in_reply_to,
            references_header,
            list_id,
            delivered_to,
            sent_at,
            Jsonb(raw_payload),
            Jsonb(metadata),
        ),
    )
    message_id = str(cur.fetchone()["id"])

    if attachments is not None:
        cur.execute("DELETE FROM attachments WHERE message_id = %s", (message_id,))
        for attachment in attachments:
            cur.execute(
                """
                INSERT INTO attachments (message_id, filename, content_type, storage_path, metadata)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    message_id,
                    attachment["filename"],
                    attachment.get("content_type"),
                    attachment.get("storage_path"),
                    Jsonb(attachment.get("metadata", {})),
                ),
            )

    cur.execute("DELETE FROM message_participants WHERE message_id = %s", (message_id,))
    for participant in participants:
        contact_id = contact_ids.get(participant.get("external_id"))
        cur.execute(
            """
            INSERT INTO message_participants (
              message_id,
              contact_id,
              participant_type,
              position,
              header_value,
              display_name,
              email,
              metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                message_id,
                contact_id,
                participant["participant_type"],
                participant.get("position", 0),
                participant.get("header_value"),
                participant.get("display_name"),
                participant.get("email"),
                Jsonb(participant.get("metadata", {})),
            ),
        )

    if chunks is not None:
        cur.execute("DELETE FROM message_chunks WHERE message_id = %s", (message_id,))
        for index, chunk in enumerate(chunks):
            embedding = chunk.get("embedding")
            if embedding is not None and len(embedding) != embedding_dimension:
                raise ValueError(
                    f"embedding length {len(embedding)} does not match EMBEDDING_DIMENSION={embedding_dimension}"
                )

            cur.execute(
                """
                INSERT INTO message_chunks (message_id, chunk_index, chunk_text, embedding_model, embedding, metadata)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    message_id,
                    chunk.get("chunk_index", index),
                    chunk["text"],
                    chunk.get("embedding_model"),
                    embedding,
                    Jsonb(chunk.get("metadata", {})),
                ),
            )

    return {
        "status": "ok",
        "message_id": message_id,
        "conversation_id": str(conversation_id),
        "chunk_count": len(chunks or []),
        "attachment_count": len(attachments or []),
        "participant_count": len(participants),
    }


def upsert_message_record_with_retry(
    cur,
    payload: dict[str, Any],
    embedding_dimension: int,
    max_attempts: int = 3,
) -> dict[str, Any]:
    for attempt in range(1, max_attempts + 1):
        try:
            with cur.connection.transaction():
                return _upsert_message_record(cur, payload, embedding_dimension)
        except psycopg_errors.DeadlockDetected as exc:
            if attempt >= max_attempts:
                raise
            delay_seconds = 0.2 * attempt
            print(
                f"warning: deadlock detected while upserting message {payload.get('external_id')}; "
                f"retrying in {delay_seconds:.1f}s ({attempt}/{max_attempts}): {exc}",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(delay_seconds)


@with_connection
def upsert_message(cur, payload: dict[str, Any], embedding_dimension: int) -> dict[str, Any]:
    return upsert_message_record_with_retry(cur, payload, embedding_dimension)


@with_connection
def health_check(cur) -> dict[str, Any]:
    return {"status": "ok", "checked_at": utc_now(), "counts": _fetch_health_counts(cur)}


@with_connection
def mailbox_status(cur) -> dict[str, Any]:
    cur.execute(
        """
        SELECT key, state, updated_at
        FROM sync_state
        ORDER BY updated_at DESC, key ASC
        """
    )
    sync_rows = cur.fetchall()
    return {
        "status": "ok",
        "checked_at": utc_now(),
        "counts": _fetch_health_counts(cur),
        "sync_state": [
            {
                "key": row["key"],
                "updated_at": row["updated_at"],
                "state": row["state"],
            }
            for row in sync_rows
        ],
    }


@with_connection
def lexical_search(cur, query: str, limit: int, source: Optional[str] = None) -> list[dict[str, Any]]:
    cur.execute(
        "SELECT * FROM search_messages_lexical(%s, %s, %s)",
        (query, limit, source),
    )
    return cur.fetchall()


@with_connection
def semantic_search(cur, query_embedding: list[float], limit: int, source: Optional[str] = None) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT
          m.id AS message_id,
          mc.chunk_index,
          m.source,
          m.external_id,
          m.conversation_id,
          m.sent_at,
          mc.chunk_text,
          mc.embedding_model,
          mc.embedding <=> %s::vector AS distance
        FROM message_chunks mc
        JOIN messages m ON m.id = mc.message_id
        WHERE mc.embedding IS NOT NULL
          AND mc.embedding_model = %s
          AND (%s::text IS NULL OR m.source = %s::text)
        ORDER BY mc.embedding <=> %s::vector ASC, m.sent_at DESC
        LIMIT %s
        """,
        (query_embedding, ACTIVE_EMBEDDING_MODEL, source, source, query_embedding, limit),
    )
    return cur.fetchall()


@with_connection
def lexical_chunk_search(cur, query: str, limit: int, source: Optional[str] = None) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT
          m.id AS message_id,
          mc.chunk_index,
          m.source,
          m.external_id,
          m.conversation_id,
          m.sent_at,
          mc.chunk_text,
          ts_rank_cd(mc.search_vector, websearch_to_tsquery('english', %s)) AS rank
        FROM message_chunks mc
        JOIN messages m ON m.id = mc.message_id
        WHERE mc.search_vector @@ websearch_to_tsquery('english', %s)
          AND (%s::text IS NULL OR m.source = %s::text)
        ORDER BY rank DESC, m.sent_at DESC
        LIMIT %s
        """,
        (query, query, source, source, limit),
    )
    return cur.fetchall()


@with_connection
def get_message_summaries(cur, message_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not message_ids:
        return {}

    cur.execute(
        """
        SELECT
          m.id,
          m.source,
          m.external_id,
          m.conversation_id,
          m.sent_at,
          m.subject,
          ma.sender_name,
          ma.sender_email,
          ma.participant_emails
        FROM messages m
        LEFT JOIN message_analysis ma ON ma.message_id = m.id
        WHERE m.id = ANY(%s::uuid[])
        """,
        (message_ids,),
    )
    rows = {}
    for row in cur.fetchall():
        row["id"] = str(row["id"])
        row["conversation_id"] = str(row["conversation_id"])
        row["url"] = build_message_url(row)
        rows[row["id"]] = row
    return rows


def search_chunks(
    query: str,
    limit: int,
    source: Optional[str],
    query_embedding: Optional[list[float]] = None,
) -> dict[str, Any]:
    lexical_rows = lexical_chunk_search(query, max(limit * 3, limit), source)
    semantic_rows: list[dict[str, Any]] = []
    if query_embedding:
        semantic_rows = semantic_search(query_embedding, max(limit * 3, limit), source)

    combined: dict[str, dict[str, Any]] = {}
    rrf_k = 60.0

    for index, row in enumerate(lexical_rows, start=1):
        key = f"{row['message_id']}:{row['chunk_index']}"
        item = combined.setdefault(
            key,
            {
                "message_id": str(row["message_id"]),
                "chunk_index": row["chunk_index"],
                "source": row["source"],
                "external_id": row["external_id"],
                "conversation_id": str(row["conversation_id"]),
                "sent_at": row["sent_at"],
                "chunk_text": row.get("chunk_text", ""),
                "score": 0.0,
                "lexical_rank": None,
                "semantic_rank": None,
            },
        )
        item["score"] += 1.0 / (rrf_k + index)
        item["lexical_rank"] = index

    for index, row in enumerate(semantic_rows, start=1):
        key = f"{row['message_id']}:{row['chunk_index']}"
        item = combined.setdefault(
            key,
            {
                "message_id": str(row["message_id"]),
                "chunk_index": row["chunk_index"],
                "source": row["source"],
                "external_id": row["external_id"],
                "conversation_id": str(row["conversation_id"]),
                "sent_at": row["sent_at"],
                "chunk_text": row.get("chunk_text", ""),
                "score": 0.0,
                "lexical_rank": None,
                "semantic_rank": None,
            },
        )
        item["score"] += 1.0 / (rrf_k + index)
        item["semantic_rank"] = index
        if not item.get("chunk_text"):
            item["chunk_text"] = row.get("chunk_text", "")

    ordered = sorted(combined.values(), key=lambda item: (item["score"], item["sent_at"]), reverse=True)[:limit]
    message_map = get_message_summaries([item["message_id"] for item in ordered])

    results = []
    for item in ordered:
        message = message_map.get(item["message_id"])
        if not message:
            continue
        snippet = (item.get("chunk_text") or "")[:700]
        results.append(
            {
                "message_id": item["message_id"],
                "chunk_index": item["chunk_index"],
                "conversation_id": item["conversation_id"],
                "sent_at": message["sent_at"],
                "subject": message.get("subject") or "(no subject)",
                "sender_name": message.get("sender_name"),
                "sender_email": message.get("sender_email"),
                "participant_emails": message.get("participant_emails") or [],
                "snippet": snippet,
                "url": message["url"],
                "score": item["score"],
                "source": item["source"],
                "external_id": item["external_id"],
                "lexical_rank": item["lexical_rank"],
                "semantic_rank": item["semantic_rank"],
            }
        )

    return {"query": query, "count": len(results), "results": results}


def investigate_mailbox(
    question: str,
    limit: int,
    source: Optional[str],
    query_embedding: Optional[list[float]] = None,
) -> dict[str, Any]:
    chunk_result = search_chunks(question, max(limit * 2, 18), source, query_embedding)
    evidence = chunk_result["results"][:limit]

    conversation_hits: dict[str, dict[str, Any]] = {}
    contact_hits: dict[str, dict[str, Any]] = {}
    domain_hits: dict[str, dict[str, Any]] = {}
    term_counts: Counter[str] = Counter()
    question_terms = set(_extract_terms(question))

    for item in evidence:
        conversation_entry = conversation_hits.setdefault(
            item["conversation_id"],
            {
                "conversation_id": item["conversation_id"],
                "subject": _normalize_subject(item.get("subject")),
                "message_ids": set(),
                "score": 0.0,
                "latest_sent_at": item["sent_at"],
            },
        )
        conversation_entry["message_ids"].add(item["message_id"])
        conversation_entry["score"] += item["score"]
        if item["sent_at"] > conversation_entry["latest_sent_at"]:
            conversation_entry["latest_sent_at"] = item["sent_at"]

        sender_email = (item.get("sender_email") or "").strip().lower()
        sender_name = item.get("sender_name")
        if sender_email:
            contact_entry = contact_hits.setdefault(
                sender_email,
                {
                    "email": sender_email,
                    "display_name": sender_name or sender_email,
                    "message_ids": set(),
                    "conversation_ids": set(),
                    "score": 0.0,
                },
            )
            contact_entry["message_ids"].add(item["message_id"])
            contact_entry["conversation_ids"].add(item["conversation_id"])
            contact_entry["score"] += item["score"]

            domain = sender_email.split("@", 1)[1] if "@" in sender_email else ""
            if domain:
                domain_entry = domain_hits.setdefault(
                    domain,
                    {"domain": domain, "message_ids": set(), "conversation_ids": set(), "score": 0.0},
                )
                domain_entry["message_ids"].add(item["message_id"])
                domain_entry["conversation_ids"].add(item["conversation_id"])
                domain_entry["score"] += item["score"]

        combined_text = " ".join(filter(None, [item.get("subject"), item.get("snippet")]))
        for term in _extract_terms(combined_text):
            if term in question_terms:
                continue
            term_counts[term] += 1

    theme_terms = [term for term, count in term_counts.most_common() if count > 1][:8]
    if not theme_terms:
        theme_terms = [term for term, _ in term_counts.most_common(8)]

    themes = []
    if theme_terms:
        themes.append(
            {
                "label": ", ".join(theme_terms[:3]),
                "summary": f"Repeated language across the strongest matching chunks points to: {', '.join(theme_terms[:5])}.",
                "terms": theme_terms[:8],
            }
        )
    if question_terms:
        overlap_terms = [term for term in theme_terms if term in question_terms]
        if overlap_terms:
            themes.append(
                {
                    "label": "question overlap",
                    "summary": f"The mailbox already contains semantically related language around: {', '.join(overlap_terms[:5])}.",
                    "terms": overlap_terms[:5],
                }
            )

    top_contacts = sorted(
        contact_hits.values(),
        key=lambda item: (len(item["message_ids"]), len(item["conversation_ids"]), item["score"]),
        reverse=True,
    )[:5]
    top_domains = sorted(
        domain_hits.values(),
        key=lambda item: (len(item["message_ids"]), len(item["conversation_ids"]), item["score"]),
        reverse=True,
    )[:5]
    top_threads = sorted(
        conversation_hits.values(),
        key=lambda item: (len(item["message_ids"]), item["score"], item["latest_sent_at"]),
        reverse=True,
    )[:5]

    connections = []
    for contact in top_contacts[:3]:
        connections.append(
            {
                "type": "contact",
                "label": contact["display_name"],
                "email": contact["email"],
                "summary": (
                    f"{contact['display_name']} appears across {len(contact['message_ids'])} relevant messages "
                    f"and {len(contact['conversation_ids'])} related conversations."
                ),
                "evidence_message_ids": sorted(contact["message_ids"])[:5],
            }
        )
    for thread in top_threads[:3]:
        connections.append(
            {
                "type": "thread",
                "label": thread["subject"],
                "conversation_id": thread["conversation_id"],
                "summary": (
                    f"The thread '{thread['subject']}' contains {len(thread['message_ids'])} of the strongest matching messages."
                ),
                "evidence_message_ids": sorted(thread["message_ids"])[:5],
            }
        )
    for domain in top_domains[:2]:
        connections.append(
            {
                "type": "domain",
                "label": domain["domain"],
                "summary": (
                    f"Messages from {domain['domain']} recur across {len(domain['message_ids'])} relevant messages "
                    f"and {len(domain['conversation_ids'])} conversations."
                ),
                "evidence_message_ids": sorted(domain["message_ids"])[:5],
            }
        )

    follow_ups = []
    if top_contacts:
        follow_ups.append(f"Fetch recent messages involving {top_contacts[0]['email']}.")
    if top_threads:
        follow_ups.append(f"Open thread {top_threads[0]['conversation_id']} for full context.")
    if theme_terms:
        follow_ups.append(f"Search again focusing on {', '.join(theme_terms[:3])}.")

    return {
        "question": question,
        "count": len(evidence),
        "themes": themes,
        "connections": connections,
        "contacts": [
            {
                "email": item["email"],
                "display_name": item["display_name"],
                "message_count": len(item["message_ids"]),
                "conversation_count": len(item["conversation_ids"]),
            }
            for item in top_contacts
        ],
        "domains": [
            {
                "domain": item["domain"],
                "message_count": len(item["message_ids"]),
                "conversation_count": len(item["conversation_ids"]),
            }
            for item in top_domains
        ],
        "threads": [
            {
                "conversation_id": item["conversation_id"],
                "subject": item["subject"],
                "message_count": len(item["message_ids"]),
                "latest_sent_at": item["latest_sent_at"],
            }
            for item in top_threads
        ],
        "evidence": evidence,
        "follow_ups": follow_ups,
    }


@with_connection
def get_thread(cur, conversation_id: str, limit: int) -> dict[str, Any]:
    cur.execute(
        """
        SELECT
          m.id,
          m.source,
          m.external_id,
          m.sent_at,
          m.subject,
          m.body_text,
          m.reply_to,
          m.message_id_header,
          m.in_reply_to,
          m.references_header,
          m.list_id,
          m.delivered_to,
          m.metadata,
          c.display_name AS sender_name,
          c.email AS sender_email,
          c.phone AS sender_phone
        FROM messages m
        LEFT JOIN contacts c ON c.id = m.sender_contact_id
        WHERE m.conversation_id = %s
        ORDER BY m.sent_at ASC
        LIMIT %s
        """,
        (conversation_id, limit),
    )
    rows = cur.fetchall()
    participants_by_message = _load_message_participants(cur, [str(row["id"]) for row in rows])
    for row in rows:
        row["participants"] = participants_by_message.get(str(row["id"]), [])
    return {"conversation_id": conversation_id, "count": len(rows), "messages": rows}


@with_connection
def get_message(cur, message_id: str) -> Optional[dict[str, Any]]:
    cur.execute(
        """
        SELECT
          m.id,
          m.source,
          m.external_id,
          m.conversation_id,
          m.sent_at,
          m.subject,
          m.body_text,
          m.body_html,
          m.reply_to,
          m.message_id_header,
          m.in_reply_to,
          m.references_header,
          m.list_id,
          m.delivered_to,
          m.raw_payload,
          m.metadata,
          c.display_name AS sender_name,
          c.email AS sender_email,
          c.phone AS sender_phone
        FROM messages m
        LEFT JOIN contacts c ON c.id = m.sender_contact_id
        WHERE m.id = %s
        """,
        (message_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    row["participants"] = _load_message_participants(cur, [str(row["id"])]).get(str(row["id"]), [])
    row["url"] = build_message_url(row)
    return row


@with_connection
def recent_messages(
    cur,
    limit: int,
    subject_query: Optional[str] = None,
    sender_email: Optional[str] = None,
    participant_email: Optional[str] = None,
) -> dict[str, Any]:
    subject_pattern = f"%{subject_query.strip().lower()}%" if subject_query else None
    cur.execute(
        """
        SELECT
          message_id,
          source,
          external_id,
          conversation_id,
          sent_at,
          subject,
          sender_name,
          sender_email,
          participant_emails
        FROM message_analysis
        WHERE (%s::text IS NULL OR LOWER(COALESCE(subject, '')) LIKE %s::text)
          AND (%s::text IS NULL OR LOWER(COALESCE(sender_email, '')) = LOWER(%s::text))
          AND (
            %s::text IS NULL
            OR EXISTS (
              SELECT 1
              FROM UNNEST(participant_emails) AS participant_email_row
              WHERE LOWER(participant_email_row) = LOWER(%s::text)
            )
          )
        ORDER BY sent_at DESC
        LIMIT %s
        """,
        (
            subject_pattern,
            subject_pattern,
            sender_email,
            sender_email,
            participant_email,
            participant_email,
            limit,
        ),
    )
    rows = cur.fetchall()
    results = []
    for row in rows:
        results.append(
            {
                "message_id": row["message_id"],
                "conversation_id": row["conversation_id"],
                "sent_at": row["sent_at"],
                "subject": row["subject"],
                "sender_name": row["sender_name"],
                "sender_email": row["sender_email"],
                "participant_emails": row["participant_emails"],
                "url": build_message_url(row),
                "source": row["source"],
                "external_id": row["external_id"],
            }
        )
    return {
        "count": len(results),
        "filters": {
            "subject_query": subject_query,
            "sender_email": sender_email,
            "participant_email": participant_email,
        },
        "results": results,
    }


@with_connection
def contact_activity(cur, limit: int, query: Optional[str] = None) -> dict[str, Any]:
    query_pattern = f"%{query.strip().lower()}%" if query else None
    cur.execute(
        """
        SELECT
          email,
          display_name,
          sent_count,
          reply_to_count,
          to_count,
          cc_count,
          bcc_count,
          message_count,
          conversation_count,
          first_seen_at,
          last_seen_at
        FROM contact_activity
        WHERE (
          %s::text IS NULL
          OR LOWER(email) LIKE %s::text
          OR LOWER(COALESCE(display_name, '')) LIKE %s::text
        )
        ORDER BY message_count DESC, last_seen_at DESC, email ASC
        LIMIT %s
        """,
        (query_pattern, query_pattern, query_pattern, limit),
    )
    rows = cur.fetchall()
    return {"count": len(rows), "query": query, "results": rows}


@with_connection
def messages_with_contact(cur, contact_email: str, limit: int) -> dict[str, Any]:
    cur.execute(
        """
        SELECT
          mwc.message_id,
          mwc.conversation_id,
          mwc.sent_at,
          mwc.subject,
          mwc.direction,
          mwc.sender_email,
          mwc.matched_roles,
          mwc.participant_emails,
          m.source,
          m.external_id
        FROM messages_with_contact(%s, %s) AS mwc
        JOIN messages m ON m.id = mwc.message_id
        ORDER BY mwc.sent_at DESC
        """,
        (contact_email, limit),
    )
    rows = cur.fetchall()
    results = []
    for row in rows:
        results.append(
            {
                "message_id": row["message_id"],
                "conversation_id": row["conversation_id"],
                "sent_at": row["sent_at"],
                "subject": row["subject"],
                "direction": row["direction"],
                "sender_email": row["sender_email"],
                "matched_roles": row["matched_roles"],
                "participant_emails": row["participant_emails"],
                "url": build_message_url(row),
                "source": row["source"],
                "external_id": row["external_id"],
            }
        )
    return {"contact_email": contact_email, "count": len(results), "results": results}


def hybrid_search(
    query: str,
    limit: int,
    source: Optional[str],
    query_embedding: Optional[list[float]] = None,
) -> dict[str, Any]:
    lexical_rows = lexical_search(query, max(limit * 3, limit), source)
    semantic_rows: list[dict[str, Any]] = []
    if query_embedding:
        semantic_rows = semantic_search(query_embedding, max(limit * 3, limit), source)

    combined: dict[str, dict[str, Any]] = {}
    rrf_k = 60.0

    for index, row in enumerate(lexical_rows, start=1):
        message_id = str(row["message_id"])
        item = combined.setdefault(
            message_id,
            {
                "id": message_id,
                "source": row["source"],
                "external_id": row["external_id"],
                "conversation_id": str(row["conversation_id"]),
                "sent_at": row["sent_at"],
                "subject": row.get("subject"),
                "snippet": row.get("body_text", "")[:400],
                "score": 0.0,
                "lexical_rank": None,
                "semantic_rank": None,
            },
        )
        item["score"] += 1.0 / (rrf_k + index)
        item["lexical_rank"] = index

    for index, row in enumerate(semantic_rows, start=1):
        message_id = str(row["message_id"])
        item = combined.setdefault(
            message_id,
            {
                "id": message_id,
                "source": row["source"],
                "external_id": row["external_id"],
                "conversation_id": str(row["conversation_id"]),
                "sent_at": row["sent_at"],
                "subject": None,
                "snippet": row.get("chunk_text", "")[:400],
                "score": 0.0,
                "lexical_rank": None,
                "semantic_rank": None,
            },
        )
        if not item.get("snippet"):
            item["snippet"] = row.get("chunk_text", "")[:400]
        item["score"] += 1.0 / (rrf_k + index)
        item["semantic_rank"] = index

    ordered = sorted(combined.values(), key=lambda item: (item["score"], item["sent_at"]), reverse=True)[:limit]
    results = []
    for row in ordered:
        message_row = get_message(row["id"])
        if not message_row:
            continue
        results.append(
            {
                "id": row["id"],
                "title": message_row.get("subject") or "(no subject)",
                "from": message_row.get("sender_email") or message_row.get("sender_name"),
                "sent_at": message_row.get("sent_at"),
                "snippet": row.get("snippet") or message_row.get("body_text", "")[:400],
                "url": message_row.get("url"),
                "score": row["score"],
                "conversation_id": row["conversation_id"],
                "source": row["source"],
                "external_id": row["external_id"],
            }
        )
    return {"query": query, "count": len(results), "results": results}


def export_message_document(message_id: str) -> Optional[dict[str, Any]]:
    row = get_message(message_id)
    if not row:
        return None
    body_text = row.get("body_text") or ""
    subject = row.get("subject") or "(no subject)"
    sender = row.get("sender_email") or row.get("sender_name") or "unknown"
    sent_at = row.get("sent_at")
    participants = row.get("participants") or []

    def format_participants(participant_type: str) -> str:
        items = []
        for participant in participants:
            if participant.get("type") != participant_type:
                continue
            display_name = participant.get("display_name")
            email = participant.get("email")
            if display_name and email and display_name != email:
                items.append(f"{display_name} <{email}>")
            elif email:
                items.append(email)
            elif display_name:
                items.append(display_name)
        return ", ".join(items)

    to_line = format_participants("to")
    cc_line = format_participants("cc")
    reply_to_line = format_participants("reply_to") or (row.get("reply_to") or "")

    header_lines = [f"Subject: {subject}", f"From: {sender}", f"Sent: {sent_at}"]
    if to_line:
        header_lines.append(f"To: {to_line}")
    if cc_line:
        header_lines.append(f"Cc: {cc_line}")
    if reply_to_line:
        header_lines.append(f"Reply-To: {reply_to_line}")

    return {
        "id": str(row["id"]),
        "title": subject,
        "url": row["url"],
        "text": "\n".join(header_lines) + f"\n\n{body_text}",
        "metadata": {
            "source": row.get("source"),
            "external_id": row.get("external_id"),
            "conversation_id": str(row.get("conversation_id")),
            "sender_name": row.get("sender_name"),
            "sender_email": row.get("sender_email"),
            "reply_to": row.get("reply_to"),
            "message_id_header": row.get("message_id_header"),
            "in_reply_to": row.get("in_reply_to"),
            "references_header": row.get("references_header"),
            "list_id": row.get("list_id"),
            "delivered_to": row.get("delivered_to"),
            "participants": participants,
            "sent_at": str(sent_at),
        },
    }

