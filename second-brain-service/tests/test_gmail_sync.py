import base64
from unittest.mock import patch

from second_brain_service.ingest import gmail_sync
from second_brain_service.search.embeddings import EmbeddingClient


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchall(self):
        return list(self.rows)


class FakeConnection:
    def __init__(self, rows):
        self._cursor = FakeCursor(rows)
        self.commit_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commit_calls += 1


def test_rehydrate_gmail_messages_rebuilds_chunks():
    rows = [
        {
            "message_id": "msg-1",
            "raw_payload": {"id": "ext-1", "threadId": "thread-1", "payload": {}},
            "existing_chunks": 1,
        }
    ]
    conn = FakeConnection(rows)
    payloads = []
    rebuilt_payload = {
        "source": "gmail",
        "external_id": "ext-1",
        "conversation_external_id": "thread-1",
        "sent_at": "2026-03-10T00:00:00+00:00",
        "sender": {"external_id": "person@example.com"},
        "participants": [],
        "attachments": [],
        "metadata": {},
        "chunks": [
            {"chunk_index": 0, "text": "Body chunk", "metadata": {"section_type": "body", "suppressed": False}},
            {"chunk_index": 1, "text": "Footer", "metadata": {"section_type": "footer", "suppressed": True}},
        ],
    }

    def fake_upsert(cur, payload, embedding_dimension):
        payloads.append(payload)
        return {"status": "ok", "chunk_count": len(payload.get("chunks") or [])}

    with patch.object(gmail_sync, "get_connection", return_value=conn), patch.object(
        gmail_sync, "normalize_gmail_message", return_value=rebuilt_payload
    ), patch.object(gmail_sync, "upsert_message_record_with_retry", side_effect=fake_upsert):
        result = gmail_sync.rehydrate_gmail_messages(limit=1)

    assert result["processed"] == 1
    assert result["failed"] == 0
    assert result["old_chunk_count"] == 1
    assert result["new_chunk_count"] == 2
    assert result["suppressed_chunk_count"] == 1
    assert payloads[0]["chunks"] == rebuilt_payload["chunks"]


def test_rehydrate_gmail_messages_tracks_failures_by_reason():
    rows = [
        {
            "message_id": "msg-1",
            "raw_payload": {"id": "ext-1", "threadId": "thread-1", "payload": {}},
            "existing_chunks": 0,
        }
    ]
    conn = FakeConnection(rows)

    with patch.object(gmail_sync, "get_connection", return_value=conn), patch.object(
        gmail_sync, "normalize_gmail_message", side_effect=ValueError("bad payload")
    ):
        result = gmail_sync.rehydrate_gmail_messages(limit=1)

    assert result["processed"] == 0
    assert result["failed"] == 1
    assert result["failure_reasons"] == {"ValueError": 1}


def test_normalize_gmail_message_rebuilds_chunks_from_raw_payload():
    raw_message = {
        "id": "ext-1",
        "threadId": "thread-1",
        "internalDate": "1710000000000",
        "snippet": "Rollback stays on Friday.",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Rollback plan"},
                {"name": "From", "value": "Alex Example <alex@example.com>"},
                {"name": "Date", "value": "Tue, 05 Mar 2024 10:00:00 +0000"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {
                        "data": base64.urlsafe_b64encode(
                            (
                                "Rollback stays on Friday at 16:00.\n\n"
                                "On Tue, Mar 5, 2024, Priya wrote:\n"
                                "> Thursday is safer.\n"
                            ).encode("utf-8")
                        ).decode("utf-8").rstrip("=")
                    },
                }
            ],
        },
    }

    payload_a = gmail_sync.normalize_gmail_message(raw_message, EmbeddingClient(enabled=False))
    payload_b = gmail_sync.normalize_gmail_message(raw_message, EmbeddingClient(enabled=False))

    assert payload_a["external_id"] == "ext-1"
    assert payload_a["conversation_external_id"] == "thread-1"
    assert payload_a["chunks"] == payload_b["chunks"]
    assert [chunk["metadata"]["section_type"] for chunk in payload_a["chunks"]] == ["body", "quote"]
