import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from agno.knowledge.document import Document
from agno.knowledge.embedder.base import Embedder
from agno.vectordb.base import VectorDb

try:
    import faiss  # type: ignore
except Exception:  # noqa: BLE001
    faiss = None


class AgnoFaissVectorDb(VectorDb):
    """Minimal AGNO VectorDb implementation backed by local FAISS files."""

    def __init__(
        self,
        *,
        index_path: str,
        metadata_path: str,
        embedder: Embedder,
        name: Optional[str] = None,
        description: Optional[str] = None,
        similarity_threshold: Optional[float] = None,
    ) -> None:
        super().__init__(name=name, description=description, similarity_threshold=similarity_threshold)
        self.index_path = Path(index_path)
        self.metadata_path = Path(metadata_path)
        self.embedder = embedder
        self._index = None
        self._rows: List[Dict[str, Any]] = []

    def _ensure_faiss(self) -> None:
        if faiss is None:
            raise RuntimeError("faiss is not installed. Install faiss-cpu to enable semantic retrieval.")

    def _load(self) -> None:
        self._ensure_faiss()
        if self._index is not None:
            return

        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        if self.metadata_path.exists():
            self._rows = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        else:
            self._rows = []

        if self.index_path.exists():
            self._index = faiss.read_index(str(self.index_path))

    def _save(self) -> None:
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        self.metadata_path.write_text(json.dumps(self._rows, ensure_ascii=True), encoding="utf-8")
        if self._index is not None:
            faiss.write_index(self._index, str(self.index_path))

    def create(self) -> None:
        self._load()
        self._save()

    async def async_create(self) -> None:
        self.create()

    def name_exists(self, name: str) -> bool:
        return False

    def async_name_exists(self, name: str) -> bool:
        return False

    def id_exists(self, id: str) -> bool:
        return False

    def content_hash_exists(self, content_hash: str) -> bool:
        return False

    def insert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        self.upsert(content_hash, documents, filters)

    async def async_insert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        self.insert(content_hash, documents, filters)

    def upsert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        self._load()
        vectors: List[List[float]] = []
        rows_to_add: List[Dict[str, Any]] = []

        for doc in documents:
            embedding = self.embedder.get_embedding(doc.content)
            if not embedding:
                continue
            vectors.append(embedding)
            rows_to_add.append(
                {
                    "content": doc.content,
                    "meta_data": doc.meta_data or {},
                    "name": doc.name,
                    "content_id": doc.content_id,
                }
            )

        if not vectors:
            return

        matrix = np.asarray(vectors, dtype="float32")
        faiss.normalize_L2(matrix)

        if self._index is None:
            self._index = faiss.IndexFlatIP(matrix.shape[1])
        self._index.add(matrix)

        self._rows.extend(rows_to_add)
        self._save()

    async def async_upsert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        self.upsert(content_hash, documents, filters)

    def search(self, query: str, limit: int = 5, filters: Optional[Any] = None) -> List[Document]:
        self._load()
        if self._index is None or not self._rows:
            return []

        query_vec = self.embedder.get_embedding(query)
        if not query_vec:
            return []

        query_matrix = np.asarray([query_vec], dtype="float32")
        faiss.normalize_L2(query_matrix)
        scores, indices = self._index.search(query_matrix, max(1, limit))

        docs: List[Document] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self._rows):
                continue
            row = self._rows[idx]
            row_meta = row.get("meta_data") or {}
            if isinstance(filters, dict):
                if not all(row_meta.get(k) == v for k, v in filters.items()):
                    continue
            if self.similarity_threshold is not None and float(score) < self.similarity_threshold:
                continue

            docs.append(
                Document(
                    content=row.get("content", ""),
                    name=row.get("name"),
                    meta_data=row_meta,
                )
            )

        return docs

    async def async_search(self, query: str, limit: int = 5, filters: Optional[Any] = None) -> List[Document]:
        return self.search(query, limit, filters)

    def drop(self) -> None:
        self.delete()

    async def async_drop(self) -> None:
        self.drop()

    def exists(self) -> bool:
        return self.index_path.exists() and self.metadata_path.exists()

    async def async_exists(self) -> bool:
        return self.exists()

    def delete(self) -> bool:
        self._index = None
        self._rows = []

        if self.index_path.exists():
            self.index_path.unlink()
        if self.metadata_path.exists():
            self.metadata_path.unlink()
        return True

    def delete_by_id(self, id: str) -> bool:
        return False

    def delete_by_name(self, name: str) -> bool:
        return False

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        return False

    def delete_by_content_id(self, content_id: str) -> bool:
        self._load()
        if not self._rows:
            return False

        remaining = [row for row in self._rows if row.get("content_id") != content_id]
        if len(remaining) == len(self._rows):
            return False

        # Rebuild index from remaining rows because IndexFlatIP does not support delete.
        self._rows = []
        self._index = None
        if self.index_path.exists():
            self.index_path.unlink()

        docs = [
            Document(content=row.get("content", ""), name=row.get("name"), meta_data=row.get("meta_data") or {})
            for row in remaining
        ]
        self.upsert(content_hash="rebuild", documents=docs)
        return True

    def get_supported_search_types(self) -> List[str]:
        return ["vector"]
