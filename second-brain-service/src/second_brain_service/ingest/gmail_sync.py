import argparse
import base64
import re
from datetime import datetime, timezone
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Any, Optional

from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from second_brain_service.common.config import DEFAULT_MAIL_SOURCE, EMBEDDING_DIMENSION
from second_brain_service.common.sanitize import sanitize_jsonish, sanitize_text
from second_brain_service.search.chunking import build_message_chunks
from second_brain_service.search.embeddings import EmbeddingClient
from second_brain_service.store.connection import get_connection
from second_brain_service.store.mail_repository import upsert_message_record_with_retry
from second_brain_service.store.maintenance import delete_sync_state, get_sync_state, set_sync_state


GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
COMMIT_INTERVAL = 25
BACKFILL_STATE_KEY = "gmail_backfill"

BOILERPLATE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"^view in browser$",
        r"^view online$",
        r"^open in browser$",
        r"^manage preferences$",
        r"^update preferences$",
        r"^email preferences$",
        r"^unsubscribe$",
        r"^unsubscribe here$",
        r"^privacy policy$",
        r"^terms( and conditions)?$",
        r"^copyright .* reserved\.?$",
        r"^this email was sent to .*$",
        r"^please do not reply to this message.*$",
        r"^did you know:.*$",
        r"^ad$",
        r"^advertisement$",
        r"^shop now$",
        r"^learn more$",
        r"^read more$",
    ]
]
TRACKING_URL_RE = re.compile(r"\(?\s*https?://[^\s)]+(?:\)|\s|$)", re.IGNORECASE)
IMAGE_MARKER_RE = re.compile(r"\[image:[^\]]+\]", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"[ \t]+")
INLINE_CTA_RE = re.compile(r"(?:shop\s*now|learn\s*more|read\s*more|buy\s*now)", re.IGNORECASE)
SENDER_DROP_PATTERNS = {
    "takealot.com": [re.compile(r"^shop top categories$", re.IGNORECASE)],
    "nytimes.com": [re.compile(r"^view in browser \| nytimes\.com$", re.IGNORECASE)],
    "google.com": [re.compile(r"^\[image: google\]$", re.IGNORECASE)],
}


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync Gmail into Postgres")
    parser.add_argument("mode", choices=["backfill", "incremental"])
    parser.add_argument("--credentials", required=True, help="Path to Google OAuth desktop client JSON")
    parser.add_argument("--token", required=True, help="Path to store Gmail OAuth token JSON")
    parser.add_argument("--query", help="Optional Gmail search query for limiting backfill scope")
    parser.add_argument("--label", action="append", default=[], help="Optional Gmail label filter")
    parser.add_argument("--max-messages", type=int, help="Optional max messages to ingest for this run")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume an interrupted backfill from the saved checkpoint in sync_state",
    )
    parser.add_argument(
        "--disable-embeddings",
        action="store_true",
        help="Store mail without vector embeddings",
    )
    return parser.parse_args(argv)


def load_credentials(credentials_path: str, token_path: str) -> Credentials:
    token_file = Path(token_path)
    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), GMAIL_SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(credentials_path, GMAIL_SCOPES)
        creds = flow.run_local_server(host="127.0.0.1", port=8765, open_browser=True)

    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json())
    return creds


def build_gmail_service(credentials_path: str, token_path: str):
    creds = load_credentials(credentials_path, token_path)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def decode_base64url(data: Optional[str]) -> str:
    if not data:
        return ""
    padding = "=" * (-len(data) % 4)
    decoded = base64.urlsafe_b64decode((data + padding).encode("utf-8"))
    return decoded.decode("utf-8", errors="replace")


def normalize_body_text(value: Optional[str]) -> str:
    if not value:
        return ""
    # Gmail marketing emails often contain NBSP and zero-width characters.
    normalized = (
        value.replace("\u00a0", " ")
        .replace("\u200b", "")
        .replace("\u200c", "")
        .replace("\u200d", "")
        .replace("\ufeff", "")
    )
    normalized = IMAGE_MARKER_RE.sub(" ", normalized)
    return "\n".join(line.strip() for line in normalized.splitlines() if line.strip()).strip()


def sender_domain(sender_email: Optional[str]) -> str:
    if not sender_email or "@" not in sender_email:
        return ""
    return sender_email.rsplit("@", 1)[1].lower()


def clean_line(line: str) -> str:
    line = normalize_body_text(line)
    if not line:
        return ""
    # Remove raw tracking URLs while preserving surrounding anchor text.
    line = TRACKING_URL_RE.sub(" ", line)
    line = INLINE_CTA_RE.sub(" ", line)
    line = re.sub(r"\(\s*\)|\[\s*\]|\{\s*\}", " ", line)
    line = re.sub(r"(?:^|\s)[\(\)\[\]\{\}\|]+(?=\s|$)", " ", line)
    line = WHITESPACE_RE.sub(" ", line).strip(" -|·•")
    return normalize_body_text(line)


def is_boilerplate(line: str, email_domain: str) -> bool:
    if not line:
        return True
    if line.isdigit() and len(line) <= 2:
        return True
    if any(pattern.match(line) for pattern in BOILERPLATE_PATTERNS):
        return True
    if email_domain:
        for suffix, patterns in SENDER_DROP_PATTERNS.items():
            if email_domain.endswith(suffix) and any(pattern.match(line) for pattern in patterns):
                return True
    return False


def clean_extracted_text(text: str, sender_email: Optional[str] = None) -> str:
    email_domain = sender_domain(sender_email)
    cleaned_lines: list[str] = []
    seen_recent: list[str] = []
    for raw_line in normalize_body_text(text).splitlines():
        line = clean_line(raw_line)
        if is_boilerplate(line, email_domain):
            continue
        # Drop consecutive duplicates and repeated short CTA text.
        if cleaned_lines and line == cleaned_lines[-1]:
            continue
        if len(line) < 80 and line in seen_recent:
            continue
        cleaned_lines.append(line)
        seen_recent = (seen_recent + [line])[-20:]
    return "\n".join(cleaned_lines).strip()


def html_to_text(html: str, sender_email: Optional[str] = None) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "meta", "title", "head"]):
        tag.decompose()

    # Preserve useful image/button labels in HTML-only marketing emails.
    for element in soup.find_all(["img", "area"]):
        attrs = element.attrs if isinstance(getattr(element, "attrs", None), dict) else {}
        alt = normalize_body_text(attrs.get("alt"))
        if alt and not alt.lower().startswith("image:"):
            element.replace_with(f" {alt} ")
        else:
            element.decompose()

    for element in soup.find_all(["a", "button"]):
        attrs = element.attrs if isinstance(getattr(element, "attrs", None), dict) else {}
        label = normalize_body_text(element.get_text(" ", strip=True))
        aria = normalize_body_text(attrs.get("aria-label"))
        title = normalize_body_text(attrs.get("title"))
        replacement = label or aria or title
        if replacement and not label:
            element.replace_with(f" {replacement} ")
        elif replacement:
            element.replace_with(f" {replacement} ")
        else:
            element.decompose()

    return clean_extracted_text(soup.get_text("\n"), sender_email)


def iter_parts(part: dict[str, Any]) -> list[dict[str, Any]]:
    parts = [part]
    for child in part.get("parts", []) or []:
        parts.extend(iter_parts(child))
    return parts


def extract_body(payload: dict[str, Any], sender_email: Optional[str] = None) -> tuple[str, Optional[str]]:
    text_parts = []
    html_parts = []
    for part in iter_parts(payload):
        mime_type = part.get("mimeType")
        body_data = part.get("body", {}).get("data")
        decoded_body = decode_base64url(body_data)
        normalized_body = normalize_body_text(decoded_body)
        if mime_type == "text/plain" and normalized_body:
            text_parts.append(normalized_body)
        elif mime_type == "text/html" and decoded_body.strip():
            html_parts.append(decoded_body)

    html_text = "\n".join(html_parts).strip() or None
    html_extracted = html_to_text(html_text, sender_email) if html_text else ""
    if text_parts:
        plain_text = clean_extracted_text("\n".join(text_parts), sender_email)
        if plain_text:
            if html_extracted and len(plain_text) < 40 and len(html_extracted) > len(plain_text) * 3:
                return html_extracted, html_text
            return plain_text, html_text
    if html_text:
        return html_extracted, html_text
    single_body = clean_extracted_text(decode_base64url(payload.get("body", {}).get("data")), sender_email)
    return single_body, html_text


def extract_headers(payload: dict[str, Any]) -> dict[str, str]:
    headers = {}
    for header in payload.get("headers", []):
        name = header.get("name")
        value = header.get("value")
        if name and value:
            headers[name.lower()] = value
    return headers


def extract_attachments(payload: dict[str, Any]) -> list[dict[str, Any]]:
    attachments = []
    for part in iter_parts(payload):
        filename = part.get("filename")
        attachment_id = part.get("body", {}).get("attachmentId")
        if filename or attachment_id:
            attachments.append(
                {
                    "filename": filename or attachment_id or "attachment",
                    "content_type": part.get("mimeType"),
                    "metadata": {
                        "attachment_id": attachment_id,
                        "size": part.get("body", {}).get("size"),
                    },
                }
            )
    return attachments


def parse_address_header(header_value: Optional[str], participant_type: str) -> list[dict[str, Any]]:
    if not header_value:
        return []

    participants = []
    for position, (display_name, email) in enumerate(getaddresses([header_value])):
        normalized_email = email.strip().lower() or None
        normalized_name = normalize_body_text(display_name) or None
        external_id = normalized_email or normalize_body_text(header_value)
        if not external_id:
            continue
        participants.append(
            {
                "participant_type": participant_type,
                "position": position,
                "external_id": external_id,
                "display_name": normalized_name or normalized_email or external_id,
                "email": normalized_email,
                "header_value": header_value,
                "metadata": {
                    "header_name": participant_type,
                    "original_header_value": header_value,
                },
            }
        )

    if participants:
        return participants

    fallback_value = normalize_body_text(header_value)
    if not fallback_value:
        return []
    return [
        {
            "participant_type": participant_type,
            "position": 0,
            "external_id": fallback_value,
            "display_name": fallback_value,
            "email": None,
            "header_value": header_value,
            "metadata": {
                "header_name": participant_type,
                "original_header_value": header_value,
                "parse_fallback": True,
            },
        }
    ]


def extract_participants(headers: dict[str, str]) -> list[dict[str, Any]]:
    participants = []
    for header_name, participant_type in (
        ("from", "from"),
        ("reply-to", "reply_to"),
        ("to", "to"),
        ("cc", "cc"),
        ("bcc", "bcc"),
    ):
        participants.extend(parse_address_header(headers.get(header_name), participant_type))
    return participants


def normalize_labels(labels: list[str]) -> list[str]:
    normalized = []
    seen = set()
    for label in labels:
        value = label.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def build_backfill_checkpoint(
    *,
    email_address: Optional[str],
    query: Optional[str],
    labels: list[str],
    max_messages: Optional[int],
    save_cursor: bool,
    next_page_token: Optional[str],
    ingested: int,
    latest_history_id: Optional[str],
    started_at: Optional[str],
) -> dict[str, Any]:
    return {
        "email_address": email_address,
        "query": query,
        "labels": labels,
        "max_messages": max_messages,
        "save_cursor": save_cursor,
        "next_page_token": next_page_token,
        "ingested": ingested,
        "latest_history_id": latest_history_id,
        "started_at": started_at or datetime.now(timezone.utc).isoformat(),
        "last_checkpoint_at": datetime.now(timezone.utc).isoformat(),
        "source": DEFAULT_MAIL_SOURCE,
        "extraction_version": "2026-03-08-c",
    }


def resolve_backfill_resume_state(
    checkpoint: dict[str, Any],
    profile_email: Optional[str],
    query: Optional[str],
    labels: list[str],
    max_messages: Optional[int],
) -> dict[str, Any]:
    checkpoint_email = checkpoint.get("email_address")
    if checkpoint_email and profile_email and checkpoint_email != profile_email:
        raise RuntimeError(
            f"Backfill checkpoint belongs to {checkpoint_email}, but Gmail returned {profile_email}."
        )

    checkpoint_query = checkpoint.get("query")
    checkpoint_labels = normalize_labels(list(checkpoint.get("labels") or []))
    checkpoint_max_messages = checkpoint.get("max_messages")

    if query is not None and query != checkpoint_query:
        raise RuntimeError(
            f"--resume requested, but --query={query!r} does not match saved checkpoint query={checkpoint_query!r}."
        )
    if labels:
        requested_labels = normalize_labels(labels)
        if requested_labels != checkpoint_labels:
            raise RuntimeError(
                f"--resume requested, but --label values {requested_labels!r} do not match saved checkpoint labels {checkpoint_labels!r}."
            )
    if max_messages is not None and max_messages != checkpoint_max_messages:
        raise RuntimeError(
            "--resume requested, but --max-messages does not match the saved checkpoint."
        )

    return {
        "query": checkpoint_query,
        "labels": checkpoint_labels,
        "max_messages": checkpoint_max_messages,
        "save_cursor": bool(checkpoint.get("save_cursor")),
        "next_page_token": checkpoint.get("next_page_token"),
        "ingested": int(checkpoint.get("ingested") or 0),
        "latest_history_id": checkpoint.get("latest_history_id"),
        "started_at": checkpoint.get("started_at"),
        "email_address": checkpoint_email or profile_email,
    }


def normalize_gmail_message(
    message: dict[str, Any],
    embedding_client: EmbeddingClient,
) -> dict[str, Any]:
    payload = message.get("payload", {})
    headers = extract_headers(payload)
    subject = sanitize_text(headers.get("subject"))
    sender_name, sender_email = parseaddr(headers.get("from", ""))
    sender_name = sanitize_text(sender_name)
    sender_email = sanitize_text(sender_email)
    body_text, body_html = extract_body(payload, sender_email)
    body_text = sanitize_text(body_text)
    body_html = sanitize_text(body_html) if body_html else None
    if not body_text:
        body_text = sanitize_text(clean_extracted_text(message.get("snippet", ""), sender_email))

    sent_at = None
    if headers.get("date"):
        try:
            sent_at = parsedate_to_datetime(headers["date"])
        except (TypeError, ValueError):
            sent_at = None
    if not sent_at:
        internal_ms = int(message.get("internalDate", "0"))
        sent_at = datetime.fromtimestamp(internal_ms / 1000, tz=timezone.utc)

    message_url = f"https://mail.google.com/mail/u/0/#all/{message['id']}"
    participants = extract_participants(headers)
    sender_participant = next((item for item in participants if item["participant_type"] == "from"), None)
    distinct_participant_emails = {item["email"] for item in participants if item.get("email")}
    chunks = build_message_chunks(subject, body_text, embedding_client, body_html=body_html, headers=headers)

    return {
        "source": DEFAULT_MAIL_SOURCE,
        "external_id": sanitize_text(message["id"]),
        "conversation_external_id": sanitize_text(message["threadId"]),
        "conversation_title": subject,
        "conversation_metadata": {"gmail_thread_id": sanitize_text(message["threadId"])},
        "subject": subject,
        "body_text": body_text,
        "body_html": body_html,
        "reply_to": sanitize_text(headers.get("reply-to")),
        "message_id_header": sanitize_text(headers.get("message-id")),
        "in_reply_to": sanitize_text(headers.get("in-reply-to")),
        "references_header": sanitize_text(headers.get("references")),
        "list_id": sanitize_text(headers.get("list-id")),
        "delivered_to": sanitize_text(headers.get("delivered-to")),
        "sent_at": sent_at.isoformat(),
        "sender": {
            "external_id": (
                sanitize_text(sender_participant.get("external_id"))
                if sender_participant
                else sender_email or sanitize_text(headers.get("from", ""))
            ),
            "display_name": (
                sanitize_text(sender_participant.get("display_name"))
                if sender_participant
                else sender_name or sender_email
            ),
            "email": sanitize_text(sender_participant.get("email")) if sender_participant else sender_email or None,
            "metadata": {"from_header": sanitize_text(headers.get("from"))},
        },
        "participants": sanitize_jsonish(participants),
        "raw_payload": sanitize_jsonish(message),
        "metadata": {
            "label_ids": sanitize_jsonish(message.get("labelIds", [])),
            "gmail_history_id": sanitize_text(message.get("historyId")),
            "gmail_internal_date": sanitize_text(message.get("internalDate")),
            "public_url": message_url,
            "headers": sanitize_jsonish(headers),
            "gmail_snippet": sanitize_text(message.get("snippet")),
            "participant_counts": {
                "from": sum(1 for item in participants if item["participant_type"] == "from"),
                "reply_to": sum(1 for item in participants if item["participant_type"] == "reply_to"),
                "to": sum(1 for item in participants if item["participant_type"] == "to"),
                "cc": sum(1 for item in participants if item["participant_type"] == "cc"),
                "bcc": sum(1 for item in participants if item["participant_type"] == "bcc"),
            },
            "distinct_participant_emails": len(distinct_participant_emails),
            "extraction_version": "2026-03-08-c",
        },
        "attachments": sanitize_jsonish(extract_attachments(payload)),
        "chunks": chunks,
    }


def unwrap_gmail_message(payload: Any) -> dict[str, Any]:
    candidate = payload
    for _ in range(8):
        if not isinstance(candidate, dict):
            break
        if candidate.get("id") and candidate.get("threadId"):
            if isinstance(candidate.get("payload"), dict):
                return candidate
            raise ValueError(
                "expected a full Gmail API message with a payload body; fetch the full message in n8n before posting it"
            )
        next_candidate = None
        for key in ("message", "gmail_message", "raw_payload", "json", "data"):
            nested = candidate.get(key)
            if isinstance(nested, dict):
                next_candidate = nested
                break
        if next_candidate is None:
            break
        candidate = next_candidate
    raise ValueError("expected a Gmail API message object with id, threadId, and payload")


def maybe_advance_gmail_history_state(history_id: Optional[str], email_address: Optional[str] = None) -> None:
    if not history_id:
        return

    state = get_sync_state("gmail")
    if not state or not state.get("history_id"):
        return

    try:
        incoming_history_id = int(str(history_id))
        current_history_id = int(str(state["history_id"]))
    except (TypeError, ValueError):
        return

    if incoming_history_id <= current_history_id:
        return

    state["history_id"] = str(history_id)
    if email_address and not state.get("email_address"):
        state["email_address"] = email_address
    state["last_n8n_ingest_at"] = datetime.now(timezone.utc).isoformat()
    set_sync_state("gmail", state)


def ingest_gmail_message(
    request_payload: dict[str, Any],
    *,
    disable_embeddings: bool = False,
) -> dict[str, Any]:
    message = unwrap_gmail_message(request_payload)
    embedding_client = EmbeddingClient(enabled=not disable_embeddings)
    payload = normalize_gmail_message(message, embedding_client)

    with get_connection() as conn:
        with conn.cursor() as cur:
            result = upsert_message_record_with_retry(cur, payload, EMBEDDING_DIMENSION)
        conn.commit()

    maybe_advance_gmail_history_state(
        payload.get("metadata", {}).get("gmail_history_id"),
        payload.get("delivered_to"),
    )

    return {
        **result,
        "source": payload["source"],
        "external_id": payload["external_id"],
        "conversation_external_id": payload["conversation_external_id"],
        "gmail_history_id": payload.get("metadata", {}).get("gmail_history_id"),
    }


def sync_backfill(
    credentials_path: str,
    token_path: str,
    query: Optional[str],
    labels: list[str],
    max_messages: Optional[int],
    disable_embeddings: bool,
    resume: bool,
) -> dict[str, Any]:
    service = build_gmail_service(credentials_path, token_path)
    embedding_client = EmbeddingClient(enabled=not disable_embeddings)
    profile = service.users().getProfile(userId="me").execute()
    profile_email = profile.get("emailAddress")

    if resume:
        checkpoint = get_sync_state(BACKFILL_STATE_KEY)
        if not checkpoint:
            raise RuntimeError("No saved backfill checkpoint found. Start a backfill first.")
        resume_state = resolve_backfill_resume_state(checkpoint, profile_email, query, labels, max_messages)
        query = resume_state["query"]
        labels = resume_state["labels"]
        max_messages = resume_state["max_messages"]
        save_cursor = resume_state["save_cursor"]
        ingested = resume_state["ingested"]
        next_page_token = resume_state["next_page_token"]
        latest_history_id = resume_state["latest_history_id"] or profile.get("historyId")
        started_at = resume_state["started_at"]
    else:
        labels = normalize_labels(labels)
        save_cursor = not query and not labels and max_messages is None
        ingested = 0
        next_page_token = None
        latest_history_id = profile.get("historyId")
        started_at = datetime.now(timezone.utc).isoformat()
        set_sync_state(
            BACKFILL_STATE_KEY,
            build_backfill_checkpoint(
                email_address=profile_email,
                query=query,
                labels=labels,
                max_messages=max_messages,
                save_cursor=save_cursor,
                next_page_token=next_page_token,
                ingested=ingested,
                latest_history_id=str(latest_history_id) if latest_history_id else None,
                started_at=started_at,
            ),
        )

    with get_connection() as conn:
        with conn.cursor() as cur:
            while True:
                if max_messages is not None and ingested >= max_messages:
                    break

                response = (
                    service.users()
                    .messages()
                    .list(
                        userId="me",
                        q=query,
                        labelIds=labels or None,
                        maxResults=min(500, max_messages - ingested) if max_messages else 500,
                        pageToken=next_page_token,
                    )
                    .execute()
                )

                for message_ref in response.get("messages", []):
                    full_message = (
                        service.users()
                        .messages()
                        .get(userId="me", id=message_ref["id"], format="full")
                        .execute()
                    )
                    latest_history_id = full_message.get("historyId", latest_history_id)
                    payload = normalize_gmail_message(full_message, embedding_client)
                    upsert_message_record_with_retry(cur, payload, EMBEDDING_DIMENSION)
                    ingested += 1
                    if ingested % COMMIT_INTERVAL == 0:
                        conn.commit()
                        print(
                            f"progress: ingested={ingested} latest_history_id={latest_history_id}",
                            flush=True,
                        )
                    if max_messages is not None and ingested >= max_messages:
                        break

                conn.commit()
                next_page_token = response.get("nextPageToken")
                if max_messages is not None and ingested >= max_messages:
                    break
                if not next_page_token:
                    break

                set_sync_state(
                    BACKFILL_STATE_KEY,
                    build_backfill_checkpoint(
                        email_address=profile_email,
                        query=query,
                        labels=labels,
                        max_messages=max_messages,
                        save_cursor=save_cursor,
                        next_page_token=next_page_token,
                        ingested=ingested,
                        latest_history_id=str(latest_history_id) if latest_history_id else None,
                        started_at=started_at,
                    ),
                )

    if save_cursor:
        set_sync_state(
            "gmail",
            {
                "history_id": str(latest_history_id) if latest_history_id else None,
                "email_address": profile_email,
                "last_backfill_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    delete_sync_state(BACKFILL_STATE_KEY)
    return {
        "status": "ok",
        "mode": "backfill",
        "ingested": ingested,
        "history_id": str(latest_history_id) if latest_history_id else None,
        "email_address": profile_email,
        "cursor_saved": save_cursor,
        "resumed": resume,
    }


def sync_incremental(
    credentials_path: str,
    token_path: str,
    max_messages: Optional[int],
    disable_embeddings: bool,
) -> dict[str, Any]:
    service = build_gmail_service(credentials_path, token_path)
    embedding_client = EmbeddingClient(enabled=not disable_embeddings)
    state = get_sync_state("gmail")
    if not state or not state.get("history_id"):
        raise RuntimeError("No Gmail history_id found in sync_state. Run backfill first.")

    history_id = state["history_id"]
    ingested = 0
    next_page_token = None
    newest_history_id = history_id

    with get_connection() as conn:
        with conn.cursor() as cur:
            while True:
                if max_messages is not None and ingested >= max_messages:
                    break

                response = (
                    service.users()
                    .history()
                    .list(
                        userId="me",
                        startHistoryId=history_id,
                        historyTypes=["messageAdded"],
                        pageToken=next_page_token,
                        maxResults=min(500, max_messages - ingested) if max_messages else 500,
                    )
                    .execute()
                )

                for history_entry in response.get("history", []):
                    newest_history_id = history_entry.get("id", newest_history_id)
                    for added in history_entry.get("messagesAdded", []):
                        message_id = added.get("message", {}).get("id")
                        if not message_id:
                            continue
                        full_message = (
                            service.users()
                            .messages()
                            .get(userId="me", id=message_id, format="full")
                            .execute()
                        )
                        payload = normalize_gmail_message(full_message, embedding_client)
                        upsert_message_record_with_retry(cur, payload, EMBEDDING_DIMENSION)
                        ingested += 1
                        if ingested % COMMIT_INTERVAL == 0:
                            conn.commit()
                            print(
                                f"progress: ingested={ingested} latest_history_id={newest_history_id}",
                                flush=True,
                            )
                        if max_messages is not None and ingested >= max_messages:
                            break
                    if max_messages is not None and ingested >= max_messages:
                        break

                conn.commit()
                next_page_token = response.get("nextPageToken")
                if not next_page_token:
                    break

    state["history_id"] = str(newest_history_id)
    set_sync_state("gmail", state)
    return {
        "status": "ok",
        "mode": "incremental",
        "ingested": ingested,
        "history_id": str(newest_history_id),
    }


def run_sync_from_args(args: argparse.Namespace) -> dict[str, Any]:
    if args.mode == "backfill":
        return sync_backfill(
            credentials_path=args.credentials,
            token_path=args.token,
            query=args.query,
            labels=args.label,
            max_messages=args.max_messages,
            disable_embeddings=args.disable_embeddings,
            resume=args.resume,
        )
    return sync_incremental(
        credentials_path=args.credentials,
        token_path=args.token,
        max_messages=args.max_messages,
        disable_embeddings=args.disable_embeddings,
    )


def rehydrate_gmail_messages(limit: Optional[int] = None) -> dict[str, Any]:
    embedding_client = EmbeddingClient(enabled=False)
    processed = 0
    skipped = 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            query = """
                SELECT raw_payload
                FROM messages
                WHERE source = %s
                  AND raw_payload <> '{}'::jsonb
                ORDER BY sent_at DESC
            """
            params: list[Any] = [DEFAULT_MAIL_SOURCE]
            if limit is not None:
                query += " LIMIT %s"
                params.append(limit)
            cur.execute(query, params)
            rows = cur.fetchall()

            for row in rows:
                raw_payload = row.get("raw_payload")
                if not isinstance(raw_payload, dict) or not raw_payload.get("id") or not raw_payload.get("threadId"):
                    skipped += 1
                    continue

                payload = normalize_gmail_message(raw_payload, embedding_client)
                payload.pop("chunks", None)
                upsert_message_record_with_retry(cur, payload, EMBEDDING_DIMENSION)
                processed += 1
                if processed % COMMIT_INTERVAL == 0:
                    conn.commit()

        conn.commit()

    return {"status": "ok", "processed": processed, "skipped": skipped, "limit": limit}


def rechunk_gmail_messages(
    limit: Optional[int] = None,
    batch_size: int = COMMIT_INTERVAL,
    dry_run: bool = False,
    disable_embeddings: bool = False,
) -> dict[str, Any]:
    """Re-chunk all stored Gmail messages using the new section-aware pipeline.

    Reads ``raw_payload`` from the ``messages`` table, re-extracts body text
    using the same extraction logic as initial ingestion, runs the new chunker,
    and replaces old chunks in-place.  No Gmail API calls are made.

    Args:
        limit: Maximum number of messages to process (``None`` = all).
        batch_size: How many messages to process between commits.
        dry_run: When ``True``, log what would happen but don't write anything.
        disable_embeddings: When ``True``, generate chunks without embeddings.
    """
    import sys

    embedding_client = EmbeddingClient(enabled=not disable_embeddings)
    processed = 0
    skipped = 0
    failed = 0
    old_chunk_count = 0
    new_chunk_count = 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            query = """
                SELECT m.id AS message_id, m.subject, m.raw_payload,
                       (SELECT COUNT(*) FROM message_chunks mc WHERE mc.message_id = m.id) AS existing_chunks
                FROM messages m
                WHERE m.source = %s
                  AND m.raw_payload <> '{}'::jsonb
                ORDER BY m.sent_at DESC
            """
            params: list[Any] = [DEFAULT_MAIL_SOURCE]
            if limit is not None:
                query += " LIMIT %s"
                params.append(limit)
            cur.execute(query, params)
            rows = cur.fetchall()

            total = len(rows)
            print(
                f"rechunk: found {total} messages to process"
                + (f" (limit={limit})" if limit else "")
                + (" [DRY RUN]" if dry_run else ""),
                file=sys.stderr,
                flush=True,
            )

            for row in rows:
                raw_payload = row.get("raw_payload")
                message_id = row.get("message_id")
                existing = row.get("existing_chunks", 0)

                if not isinstance(raw_payload, dict) or not raw_payload.get("id"):
                    skipped += 1
                    continue

                try:
                    # Re-extract body text using the same path as initial ingestion
                    payload_inner = raw_payload.get("payload", {})
                    headers = extract_headers(payload_inner)
                    subject = sanitize_text(headers.get("subject"))
                    _, sender_email = parseaddr(headers.get("from", ""))
                    sender_email = sanitize_text(sender_email)
                    body_text, body_html = extract_body(payload_inner, sender_email)
                    body_text = sanitize_text(body_text)
                    body_html = sanitize_text(body_html) if body_html else None
                    if not body_text:
                        body_text = sanitize_text(
                            clean_extracted_text(raw_payload.get("snippet", ""), sender_email)
                        )

                    chunks = build_message_chunks(
                        subject, body_text, embedding_client,
                        body_html=body_html, headers=headers,
                    )

                    old_chunk_count += existing
                    new_chunk_count += len(chunks)

                    if not dry_run:
                        # Replace old chunks with new ones
                        from psycopg.types.json import Jsonb

                        cur.execute(
                            "DELETE FROM message_chunks WHERE message_id = %s",
                            (message_id,),
                        )
                        for chunk in chunks:
                            embedding = chunk.get("embedding")
                            if embedding is not None and len(embedding) != EMBEDDING_DIMENSION:
                                raise ValueError(
                                    f"embedding length {len(embedding)} != EMBEDDING_DIMENSION={EMBEDDING_DIMENSION}"
                                )
                            cur.execute(
                                """
                                INSERT INTO message_chunks
                                    (message_id, chunk_index, chunk_text, embedding_model, embedding, metadata)
                                VALUES (%s, %s, %s, %s, %s, %s)
                                """,
                                (
                                    message_id,
                                    chunk.get("chunk_index", 0),
                                    chunk["text"],
                                    chunk.get("embedding_model"),
                                    embedding,
                                    Jsonb(chunk.get("metadata", {})),
                                ),
                            )

                    processed += 1

                    if processed % batch_size == 0:
                        if not dry_run:
                            conn.commit()
                        print(
                            f"rechunk: progress {processed}/{total}"
                            f" (old_chunks={old_chunk_count}, new_chunks={new_chunk_count})",
                            file=sys.stderr,
                            flush=True,
                        )

                except Exception as exc:
                    failed += 1
                    print(
                        f"rechunk: failed message_id={message_id}: {exc}",
                        file=sys.stderr,
                        flush=True,
                    )
                    # Roll back the current transaction savepoint but keep going
                    conn.rollback()
                    continue

            if not dry_run:
                conn.commit()

    result = {
        "status": "ok",
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "old_chunk_count": old_chunk_count,
        "new_chunk_count": new_chunk_count,
        "dry_run": dry_run,
    }
    if limit is not None:
        result["limit"] = limit

    print(
        f"rechunk: done — processed={processed} skipped={skipped} failed={failed}"
        f" old_chunks={old_chunk_count} new_chunks={new_chunk_count}"
        + (" [DRY RUN]" if dry_run else ""),
        file=sys.stderr,
        flush=True,
    )
    return result
