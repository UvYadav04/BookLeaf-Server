from __future__ import annotations

import logging
import uuid
from typing import Any

from fastembed import TextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from .config import settings

logger = logging.getLogger(__name__)


class TicketVectors:
    _instance: TicketVectors | None = None

    def __new__(cls) -> TicketVectors:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self.qdrant_url = settings.qdrant_url
        self.qdrant_api_key = settings.qdrant_api_key
        self.collection_name = settings.qdrant_collection

        if not self.qdrant_url:
            raise ValueError("QDRANT_URL is missing")
        if not self.collection_name:
            raise ValueError("QDRANT_COLLECTION_NAME is missing")

        self.client = QdrantClient(url=self.qdrant_url, api_key=self.qdrant_api_key)
        self.embedding_model_name = "BAAI/bge-small-en-v1.5"
        self.embedder = TextEmbedding(model_name=self.embedding_model_name)
        self.vector_size = 384
        self._ensure_collection()
        self._initialized = True

    def _ensure_collection(self) -> None:
        collections = self.client.get_collections()
        exists = any(col.name == self.collection_name for col in collections.collections)
        if exists:
            logger.info('Qdrant collection "%s" already exists', self.collection_name)
            return

        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=self.vector_size, distance=Distance.COSINE),
        )

        for field in ("status", "book_id", "category", "priority", "keyword"):
            try:
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field,
                    field_schema="keyword",
                )
                logger.info('Created payload index for "%s"', field)
            except Exception as exc:  # noqa: BLE001
                logger.warning('Payload index "%s" may already exist: %s', field, exc)

        logger.info('Qdrant collection "%s" created', self.collection_name)

    def _text(self, title: str, description: str) -> str:
        return f"Ticket Title:\n{title}\n\nTicket Description:\n{description}".strip()

    def create_embedding(self, text: str) -> list[float]:
        embedding = next(self.embedder.embed([text]))
        return embedding.tolist()

    def add_ticket(self, title: str, description: str, metadata: dict[str, Any] | None = None) -> str:
        metadata = metadata or {}
        searchable_text = self._text(title=title, description=description)
        embedding = self.create_embedding(searchable_text)
        point_id = str(uuid.uuid4())

        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        "title": title,
                        "description": description,
                        "searchable_text": searchable_text,
                        **metadata,
                    },
                )
            ],
            wait=True,
        )
        return point_id

    def _build_filter(self, filters: dict[str, Any] | None) -> Filter | None:
        if not filters:
            return None
        conditions = [
            FieldCondition(key=key, match=MatchValue(value=value))
            for key, value in filters.items()
            if value is not None
        ]
        return Filter(must=conditions) if conditions else None

    def search_tickets(
        self,
        title: str,
        description: str,
        limit: int = 5,
        score_threshold: float = 0.7,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        searchable_text = self._text(title=title, description=description)
        embedding = self.create_embedding(searchable_text)

        results = self.client.query_points(
        collection_name=self.collection_name,
        query=embedding,
        limit=limit,
        score_threshold=score_threshold,
        query_filter=self._build_filter(filters),
        with_payload=True,)


        points = results.points

        return [
            {
                "id": item.id,
                "score": item.score,
                "payload": item.payload,
            }
            for item in points
        ]

    def delete_ticket(self, point_id: str) -> bool:
        self.client.delete(collection_name=self.collection_name, points_selector=[point_id], wait=True)
        return True


TicketVectorStore = TicketVectors
ticket_vectors = TicketVectors()
ticket_vector_store = ticket_vectors
