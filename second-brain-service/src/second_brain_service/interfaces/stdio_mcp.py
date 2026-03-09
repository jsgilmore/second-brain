import json
import sys
from typing import Any, Optional

from second_brain_service.common.config import DEFAULT_MAIL_SOURCE
from second_brain_service.search.embeddings import EmbeddingClient
from second_brain_service.search.retrieval import (
    contact_activity,
    get_thread,
    hybrid_search,
    investigate_mailbox,
    mailbox_status,
    messages_with_contact,
    recent_messages,
    search_chunks,
)
from second_brain_service.store.mail_repository import export_message_document


def make_tool_response(data: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


TOOLS = [
    {
        "name": "search",
        "description": "Search Gmail messages using hybrid full-text and semantic retrieval.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_chunks",
        "description": "Search semantically relevant email chunks instead of whole messages.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "fetch",
        "description": "Fetch a Gmail message by internal message id from search results.",
        "inputSchema": {
            "type": "object",
            "properties": {"message_id": {"type": "string"}},
            "required": ["message_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "fetch_thread",
        "description": "Fetch a message thread by conversation id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            "required": ["conversation_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "status",
        "description": "Return database health, record counts, and sync state.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "recent_mail",
        "description": "List recent messages with optional subject, sender, or participant filters.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                "subject_query": {"type": "string"},
                "sender_email": {"type": "string"},
                "participant_email": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "contacts",
        "description": "List high-activity contacts, optionally filtered by name or email.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                "query": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "contact_messages",
        "description": "List messages involving a specific email address.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "contact_email": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": ["contact_email"],
            "additionalProperties": False,
        },
    },
    {
        "name": "investigate",
        "description": "Investigate a question against the mailbox and return likely connections, themes, and evidence.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["question"],
            "additionalProperties": False,
        },
    },
]


def call_tool(name: str, arguments: dict[str, Any], embedding_client: EmbeddingClient) -> dict[str, Any]:
    if name == "search":
        query = arguments["query"]
        query_embedding = embedding_client.embed_query(query) if embedding_client.enabled else None
        return make_tool_response(
            hybrid_search(query=query, limit=arguments.get("limit", 8), source=DEFAULT_MAIL_SOURCE, query_embedding=query_embedding)
        )
    if name == "search_chunks":
        query = arguments["query"]
        query_embedding = embedding_client.embed_query(query) if embedding_client.enabled else None
        return make_tool_response(
            search_chunks(
                query=query,
                limit=arguments.get("limit", 8),
                source=DEFAULT_MAIL_SOURCE,
                query_embedding=query_embedding,
            )
        )
    if name == "fetch":
        document = export_message_document(arguments["message_id"])
        if not document:
            raise ValueError(f"message not found: {arguments['message_id']}")
        return make_tool_response(document)
    if name == "fetch_thread":
        return make_tool_response(get_thread(arguments["conversation_id"], arguments.get("limit", 200)))
    if name == "status":
        return make_tool_response(mailbox_status())
    if name == "recent_mail":
        return make_tool_response(
            recent_messages(
                limit=arguments.get("limit", 20),
                subject_query=arguments.get("subject_query"),
                sender_email=arguments.get("sender_email"),
                participant_email=arguments.get("participant_email"),
            )
        )
    if name == "contacts":
        return make_tool_response(contact_activity(limit=arguments.get("limit", 20), query=arguments.get("query")))
    if name == "contact_messages":
        return make_tool_response(
            messages_with_contact(contact_email=arguments["contact_email"], limit=arguments.get("limit", 20))
        )
    if name == "investigate":
        question = arguments["question"]
        query_embedding = embedding_client.embed_query(question) if embedding_client.enabled else None
        return make_tool_response(
            investigate_mailbox(
                question=question,
                limit=arguments.get("limit", 12),
                source=DEFAULT_MAIL_SOURCE,
                query_embedding=query_embedding,
            )
        )
    raise ValueError(f"unknown tool: {name}")


def read_mcp_message() -> Optional[dict[str, Any]]:
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        header_name, header_value = line.decode("utf-8").split(":", 1)
        headers[header_name.strip().lower()] = header_value.strip()

    content_length = int(headers.get("content-length", "0"))
    if content_length == 0:
        return None
    body = sys.stdin.buffer.read(content_length)
    return json.loads(body.decode("utf-8"))


def write_mcp_message(payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, default=str).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(encoded)}\r\n\r\n".encode("utf-8"))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def serve_stdio_mcp() -> None:
    embedding_client = EmbeddingClient()
    while True:
        message = read_mcp_message()
        if message is None:
            return

        method = message.get("method")
        message_id = message.get("id")

        try:
            if method == "initialize":
                write_mcp_message(
                    {
                        "jsonrpc": "2.0",
                        "id": message_id,
                        "result": {
                            "protocolVersion": message.get("params", {}).get("protocolVersion", "2024-11-05"),
                            "serverInfo": {"name": "gmail-second-brain", "version": "0.2.0"},
                            "capabilities": {"tools": {}},
                        },
                    }
                )
                continue

            if method == "notifications/initialized":
                continue

            if method == "tools/list":
                write_mcp_message({"jsonrpc": "2.0", "id": message_id, "result": {"tools": TOOLS}})
                continue

            if method == "tools/call":
                params = message.get("params", {})
                result = call_tool(params["name"], params.get("arguments", {}), embedding_client)
                write_mcp_message({"jsonrpc": "2.0", "id": message_id, "result": result})
                continue

            write_mcp_message(
                {
                    "jsonrpc": "2.0",
                    "id": message_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }
            )
        except Exception as exc:
            write_mcp_message(
                {"jsonrpc": "2.0", "id": message_id, "error": {"code": -32000, "message": str(exc)}}
            )
