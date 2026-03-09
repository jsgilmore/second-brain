import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from second_brain_service.common.config import API_PORT, DEFAULT_MAIL_SOURCE, EMBEDDING_DIMENSION
from second_brain_service.ingest.gmail_sync import ingest_gmail_message
from second_brain_service.search.embeddings import EmbeddingClient
from second_brain_service.search.retrieval import get_thread, hybrid_search
from second_brain_service.store.mail_repository import export_message_document, health_check, upsert_message


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "SecondBrainMail/0.2"

    def _write_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Any:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length == 0:
            return {}
        return json.loads(self.rfile.read(content_length).decode("utf-8"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self._write_json(200, health_check())
            return

        if parsed.path.startswith("/messages/"):
            message_id = parsed.path.split("/")[2]
            document = export_message_document(message_id)
            if not document:
                self._write_json(404, {"error": "not_found"})
                return
            self._write_json(200, document)
            return

        if parsed.path.startswith("/conversations/") and parsed.path.endswith("/messages"):
            conversation_id = parsed.path.split("/")[2]
            query_params = parse_qs(parsed.query)
            limit = int(query_params.get("limit", ["100"])[0])
            self._write_json(200, get_thread(conversation_id, limit))
            return

        self._write_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        embedding_client = EmbeddingClient()
        try:
            parsed = urlparse(self.path)
            payload = self._read_json()
            if not isinstance(payload, dict):
                self._write_json(400, {"error": "invalid_json", "message": "expected a JSON object body"})
                return

            if parsed.path == "/ingest/gmail":
                disable_embeddings = bool(payload.get("disable_embeddings", False))
                self._write_json(200, ingest_gmail_message(payload, disable_embeddings=disable_embeddings))
                return

            if parsed.path == "/ingest/message":
                required = ["source", "external_id", "conversation_external_id", "sent_at"]
                missing = [key for key in required if key not in payload]
                if missing:
                    self._write_json(400, {"error": "missing_fields", "fields": missing})
                    return
                self._write_json(200, upsert_message(payload, EMBEDDING_DIMENSION))
                return

            if parsed.path == "/search":
                if "query" not in payload:
                    self._write_json(400, {"error": "missing_query"})
                    return
                limit = int(payload.get("limit", 10))
                source = payload.get("source", DEFAULT_MAIL_SOURCE)
                query_embedding = embedding_client.embed_query(payload["query"]) if embedding_client.enabled else None
                self._write_json(
                    200,
                    hybrid_search(
                        query=payload["query"],
                        limit=limit,
                        source=source,
                        query_embedding=query_embedding,
                    ),
                )
                return

            self._write_json(404, {"error": "not_found"})
        except ValueError as exc:
            self._write_json(400, {"error": "validation_error", "message": str(exc)})
        except Exception as exc:
            self._write_json(500, {"error": "internal_error", "message": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format % args))


def serve_http() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", API_PORT), ApiHandler)
    print(f"http api listening on 0.0.0.0:{API_PORT}", flush=True)
    server.serve_forever()
