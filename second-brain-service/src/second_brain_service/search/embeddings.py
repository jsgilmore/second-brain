import json
import sys
from typing import Optional
from urllib import request
from urllib.error import HTTPError

from openai import OpenAI

from second_brain_service.common.config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    EMBEDDING_PROVIDER,
    EMBED_QUERY_PREFIX,
    OLLAMA_BASE_URL,
    OLLAMA_EMBEDDING_MODEL,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_EMBEDDING_MODEL,
)
from second_brain_service.common.sanitize import sanitize_text


class EmbeddingClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        enabled: bool = True,
        provider: Optional[str] = None,
    ) -> None:
        self.provider = (provider or EMBEDDING_PROVIDER).strip().lower()
        self.api_key = api_key or OPENAI_API_KEY
        self.base_url = base_url or (OLLAMA_BASE_URL if self.provider == "ollama" else OPENAI_BASE_URL)
        self.model = model or (OLLAMA_EMBEDDING_MODEL if self.provider == "ollama" else OPENAI_EMBEDDING_MODEL)
        self.client = None
        self._enabled = enabled
        if not enabled:
            return
        if self.provider == "openai":
            if not self.api_key:
                return
            kwargs = {"api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self.client = OpenAI(**kwargs)
            return
        if self.provider == "ollama":
            return
        raise ValueError(f"unsupported embedding provider: {self.provider}")

    @property
    def enabled(self) -> bool:
        if not self._enabled:
            return False
        if self.provider == "ollama":
            return True
        return self.client is not None

    def _embed_with_ollama(self, texts: list[str]) -> list[Optional[list[float]]]:
        embeddings: list[Optional[list[float]]] = []
        for text in texts:
            sanitized_text = sanitize_text(text)
            payload = json.dumps({"model": self.model, "input": sanitized_text}).encode("utf-8")
            req = request.Request(
                f"{self.base_url}/api/embed",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with request.urlopen(req, timeout=120) as response:
                    data = json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                details = exc.read().decode("utf-8", errors="replace")
                print(
                    f"warning: ollama embedding failed for chunk; status={exc.code} details={details[:400]}",
                    file=sys.stderr,
                    flush=True,
                )
                embeddings.append(None)
                continue
            item_embeddings = data.get("embeddings", [])
            if not item_embeddings:
                print("warning: ollama returned no embeddings for chunk", file=sys.stderr, flush=True)
                embeddings.append(None)
                continue
            embeddings.append(item_embeddings[0])
        return embeddings

    def embed_texts(self, texts: list[str]) -> list[Optional[list[float]]]:
        if not texts:
            return []
        sanitized_texts = [sanitize_text(text) for text in texts]
        if self.provider == "ollama":
            return self._embed_with_ollama(sanitized_texts)
        if not self.client:
            raise RuntimeError("OPENAI_API_KEY is not set; embeddings are unavailable")
        try:
            response = self.client.embeddings.create(model=self.model, input=sanitized_texts)
            return [item.embedding for item in response.data]
        except Exception as exc:
            print(
                f"warning: batch embedding request failed; falling back to per-chunk embedding: {exc}",
                file=sys.stderr,
                flush=True,
            )

        embeddings: list[Optional[list[float]]] = []
        for index, text in enumerate(sanitized_texts):
            try:
                response = self.client.embeddings.create(model=self.model, input=text)
                embeddings.append(response.data[0].embedding if response.data else None)
            except Exception as exc:
                print(
                    f"warning: embedding failed for chunk {index}; storing message chunk without embedding: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
                embeddings.append(None)
        return embeddings

    def embed_query(self, text: str) -> Optional[list[float]]:
        if not self.enabled:
            return None
        query_text = f"{EMBED_QUERY_PREFIX}{sanitize_text(text)}" if EMBED_QUERY_PREFIX else sanitize_text(text)
        return self.embed_texts([query_text])[0]


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    cleaned = " ".join(text.split())
    if not cleaned:
        return []
    if len(cleaned) <= chunk_size:
        return [cleaned]

    chunks = []
    start = 0
    while start < len(cleaned):
        end = min(start + chunk_size, len(cleaned))
        if end < len(cleaned):
            split_at = cleaned.rfind(" ", start, end)
            if split_at > start + 200:
                end = split_at
        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(cleaned):
            break
        start = max(end - overlap, start + 1)
    return chunks


def build_message_chunks(subject: Optional[str], body_text: str, embedding_client: EmbeddingClient) -> list[dict]:
    prefix = f"Subject: {subject}\n\n" if subject else ""
    chunk_texts = chunk_text(f"{prefix}{body_text}".strip())
    if not chunk_texts:
        return []

    embeddings = embedding_client.embed_texts(chunk_texts) if embedding_client.enabled else [None] * len(chunk_texts)
    chunks = []
    for index, text in enumerate(chunk_texts):
        chunk = {"chunk_index": index, "text": text}
        if embeddings[index] is not None:
            chunk["embedding_model"] = embedding_client.model
            chunk["embedding"] = embeddings[index]
        chunks.append(chunk)
    return chunks
