import os
import uuid
from typing import Any, Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams, PointStruct

from fastembed import TextEmbedding
from .config import settings

class TicketVectorStore:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TicketVectorStore, cls).__new__(cls)

        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return

        self.qdrant_url = settings.qdrant_url
        self.qdrant_api_key = settings.qdrant_api_key
        self.collection_name = settings.qdrant_collection

        if not self.qdrant_url:
            raise ValueError("QDRANT_URL is missing")

        if not self.collection_name:
            raise ValueError("QDRANT_COLLECTION_NAME is missing")

        self.client = QdrantClient(
            url=self.qdrant_url,
            api_key=self.qdrant_api_key,
        )

        self.embedding_model_name = "BAAI/bge-small-en-v1.5"

        self.embedder = TextEmbedding(
            model_name=self.embedding_model_name
        )

        self.vector_size = 384

        self._ensure_collection()

        self._initialized = True

    def _ensure_collection(self):
        collections = self.client.get_collections()

        exists = any(
            collection.name == self.collection_name
            for collection in collections.collections
        )

        if exists:
            print(
            f'Deleting existing collection "{self.collection_name}"'
        )

            self.client.delete_collection(
            collection_name=self.collection_name)

        if exists:
            print(
                f'Collection "{self.collection_name}" already exists'
            )

            return

        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(
                size=self.vector_size,
                distance=Distance.COSINE,
            ),
        )

        indexed_fields = [
        "status",
        "book_id",
        "category",
        "priority",
        "keyword",
        ]

        for field in indexed_fields:
            try:
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field,
                    field_schema="keyword",
                )

                print(f'Created index for "{field}"')

            except Exception as e:
                print(
                    f'Index "{field}" may already exist: {str(e)}'
                )

        print(
            f'Collection "{self.collection_name}" created successfully'
        )

    def _build_searchable_text(
        self,
        title: str,
        description: str,
    ) -> str:
        return f"""
Ticket Title:
{title}

Ticket Description:
{description}
        """.strip()

    def create_embedding(self, text: str) -> List[float]:
        embedding_generator = self.embedder.embed([text])

        embedding = next(embedding_generator)

        return embedding.tolist()

    def add_ticket(
        self,
        title: str,
        description: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        metadata = metadata or {}

        searchable_text = self._build_searchable_text(
            title=title,
            description=description,
        )

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

    def search_tickets(
        self,
        title: str,
        description: str,
        limit: int = 5,
        score_threshold: float = 0.7,
        filters: Optional[Dict[str, Any]] = None,
    ):
        searchable_text = self._build_searchable_text(
            title=title,
            description=description,
        )

        embedding = self.create_embedding(searchable_text)

        query_filter = None

        if filters:
            from qdrant_client.http.models import (
                Filter,
                FieldCondition,
                MatchValue,
            )

            conditions = [
                FieldCondition(
                    key=key,
                    match=MatchValue(value=value),
                )
                for key, value in filters.items()
            ]

            query_filter = Filter(must=conditions)

        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=embedding,
            limit=limit,
            score_threshold=score_threshold,
            query_filter=query_filter,
            with_payload=True,
        )

        formatted_results = []

        for result in results:
            formatted_results.append(
                {
                    "id": result.id,
                    "score": result.score,
                    "payload": result.payload,
                }
            )

        return formatted_results

    def delete_ticket(self, point_id: str):
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=[point_id],
            wait=True,
        )

        return True


ticket_vector_store = TicketVectorStore()