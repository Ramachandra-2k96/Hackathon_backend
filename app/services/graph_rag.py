import json
import re
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from itertools import combinations
from pathlib import Path
from typing import Iterable

from agno.knowledge.document import Document
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
import httpx
from openai import OpenAI
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.storage import storage
from app.models.project import (
    Project,
    ProjectDocCommunity,
    ProjectDocNode,
    ProjectDocRelation,
)
from app.services.agno_faiss import AgnoFaissVectorDb


ENTITY_PATTERN = re.compile(
    r"entity_name:\s*(.+?)\s*entity_type:\s*(.+?)\s*entity_description:\s*(.+?)\s*(?=entity_name:|source_entity:|$)",
    re.IGNORECASE | re.DOTALL,
)
RELATION_PATTERN = re.compile(
    r"source_entity:\s*(.+?)\s*target_entity:\s*(.+?)\s*relation:\s*(.+?)\s*relationship_description:\s*(.+?)\s*(?=source_entity:|$)",
    re.IGNORECASE | re.DOTALL,
)

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 180
MAX_PAIRS_PER_CHUNK = 8
TOP_COMMUNITIES = 4
TOP_CHUNKS = 6
SEMANTIC_INDEX_ROOT = Path("uploads/graphrag_indexes")


@dataclass
class EntityCandidate:
    key: str
    name: str
    entity_type: str
    description: str


@dataclass
class RelationCandidate:
    source_key: str
    target_key: str
    relation: str
    description: str


class GraphRAGService:
    def __init__(self) -> None:
        http_client = httpx.Client(verify=settings.OPENAI_VERIFY_SSL)
        self._client = (
            OpenAI(
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_BASE_URL,
                http_client=http_client,
            )
            if settings.OPENAI_API_KEY
            else None
        )
        self._embedder = (
            OpenAIEmbedder(
                id="text-embedding-3-small",
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_BASE_URL,
                client_params={"http_client": http_client},
            )
            if settings.OPENAI_API_KEY
            else None
        )
        self._knowledge_cache: dict[int, Knowledge] = {}

    def build_index(self, db: Session, project: Project) -> tuple[int, int, int]:
        docs = self._load_markdown_docs(project)
        if not docs:
            raise ValueError("No markdown documentation found in project source")

        entities_map: dict[str, EntityCandidate] = {}
        relations: list[RelationCandidate] = []
        chunk_documents: list[Document] = []

        for doc_path, doc_text in docs:
            for chunk_index, chunk in enumerate(self._chunk_text(doc_text)):
                chunk_documents.append(
                    Document(
                        content=chunk,
                        name=doc_path,
                        meta_data={"doc_path": doc_path, "chunk_index": chunk_index},
                    )
                )
                chunk_entities, chunk_relations = self._extract_from_chunk(chunk)
                for entity in chunk_entities:
                    if entity.key not in entities_map:
                        entities_map[entity.key] = entity
                relations.extend(chunk_relations)

        if not entities_map:
            raise ValueError("No graph entities extracted from markdown documentation")

        relations = [r for r in relations if r.source_key in entities_map and r.target_key in entities_map]

        community_map = self._build_communities(entities_map.keys(), relations)
        community_summaries = self._summarize_communities(entities_map, relations, community_map)

        self._replace_project_graph(db, project, entities_map, relations, community_summaries)
        self._build_semantic_index(project.id, chunk_documents)

        project.docs_index_status = "ready"
        project.docs_index_error = None
        project.docs_indexed_at = datetime.now(timezone.utc)
        project.docs_nodes_count = len(entities_map)
        project.docs_relations_count = len(relations)
        project.docs_communities_count = len(community_summaries)

        db.add(project)
        db.commit()
        db.refresh(project)
        return project.docs_nodes_count, project.docs_relations_count, project.docs_communities_count

    def answer_query(self, db: Session, project: Project, query: str) -> str:
        summaries = (
            db.query(ProjectDocCommunity)
            .filter(ProjectDocCommunity.project_id == project.id)
            .order_by(ProjectDocCommunity.community_key.asc())
            .all()
        )
        semantic_chunks = self._retrieve_semantic_chunks(project.id, query)

        if not summaries and not semantic_chunks:
            return (
                "I do not have an indexed documentation graph and chunk index for this project yet. "
                "Run project preprocessing first, then ask again."
            )

        scored = []
        query_terms = self._tokenize(query)
        for community in summaries:
            summary_terms = self._tokenize(community.summary)
            overlap = len(query_terms.intersection(summary_terms))
            scored.append((overlap, community.summary))

        scored.sort(key=lambda item: item[0], reverse=True)
        selected = [summary for _, summary in scored[:TOP_COMMUNITIES]]

        partial_answers = [self._answer_from_summary(summary, query) for summary in selected]
        if semantic_chunks:
            partial_answers.append(self._answer_from_chunks(semantic_chunks, query))

        return self._aggregate_answers(partial_answers, query)

    @staticmethod
    def _semantic_paths(project_id: int) -> tuple[Path, Path, Path]:
        project_dir = SEMANTIC_INDEX_ROOT / f"project_{project_id}"
        return project_dir / "chunks.faiss", project_dir / "chunks_meta.json", project_dir / "chunks_raw.json"

    def _build_semantic_index(self, project_id: int, chunk_documents: list[Document]) -> None:
        index_path, meta_path, raw_path = self._semantic_paths(project_id)
        index_path.parent.mkdir(parents=True, exist_ok=True)

        raw_records = [
            {
                "content": doc.content,
                "doc_path": doc.meta_data.get("doc_path"),
                "chunk_index": doc.meta_data.get("chunk_index"),
            }
            for doc in chunk_documents
        ]
        raw_path.write_text(json.dumps(raw_records, ensure_ascii=True), encoding="utf-8")

        if not self._embedder:
            self._knowledge_cache.pop(project_id, None)
            return

        vector_db = AgnoFaissVectorDb(
            index_path=str(index_path),
            metadata_path=str(meta_path),
            embedder=self._embedder,
            name=f"project_{project_id}_faiss",
        )
        vector_db.delete()
        vector_db.upsert(content_hash=f"project_{project_id}", documents=chunk_documents)

        self._knowledge_cache[project_id] = Knowledge(
            name=f"project_{project_id}_knowledge",
            vector_db=vector_db,
            max_results=TOP_CHUNKS,
        )

    def _get_project_knowledge(self, project_id: int) -> Knowledge | None:
        if project_id in self._knowledge_cache:
            return self._knowledge_cache[project_id]

        if not self._embedder:
            return None

        index_path, meta_path, _ = self._semantic_paths(project_id)
        if not index_path.exists() or not meta_path.exists():
            return None

        vector_db = AgnoFaissVectorDb(
            index_path=str(index_path),
            metadata_path=str(meta_path),
            embedder=self._embedder,
            name=f"project_{project_id}_faiss",
        )
        knowledge = Knowledge(
            name=f"project_{project_id}_knowledge",
            vector_db=vector_db,
            max_results=TOP_CHUNKS,
        )
        self._knowledge_cache[project_id] = knowledge
        return knowledge

    def _retrieve_semantic_chunks(self, project_id: int, query: str) -> list[str]:
        knowledge = self._get_project_knowledge(project_id)
        if knowledge is not None:
            docs = knowledge.search(query=query, max_results=TOP_CHUNKS)
            if docs:
                return [
                    f"[{doc.meta_data.get('doc_path', 'unknown')}#chunk{doc.meta_data.get('chunk_index', '?')}] {doc.content}"
                    for doc in docs
                ]

        return self._retrieve_lexical_chunks(project_id, query)

    def _retrieve_lexical_chunks(self, project_id: int, query: str) -> list[str]:
        _, _, raw_path = self._semantic_paths(project_id)
        if not raw_path.exists():
            return []

        raw_chunks = json.loads(raw_path.read_text(encoding="utf-8"))
        query_terms = self._tokenize(query)
        scored: list[tuple[int, str]] = []
        for row in raw_chunks:
            content = row.get("content", "")
            if not content:
                continue
            overlap = len(query_terms.intersection(self._tokenize(content)))
            chunk_label = f"[{row.get('doc_path', 'unknown')}#chunk{row.get('chunk_index', '?')}]"
            scored.append((overlap, f"{chunk_label} {content}"))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [chunk for _, chunk in scored[:TOP_CHUNKS] if chunk]

    def _replace_project_graph(
        self,
        db: Session,
        project: Project,
        entities_map: dict[str, EntityCandidate],
        relations: list[RelationCandidate],
        community_summaries: dict[str, str],
    ) -> None:
        db.query(ProjectDocRelation).filter(ProjectDocRelation.project_id == project.id).delete()
        db.query(ProjectDocNode).filter(ProjectDocNode.project_id == project.id).delete()
        db.query(ProjectDocCommunity).filter(ProjectDocCommunity.project_id == project.id).delete()

        for entity in entities_map.values():
            db.add(
                ProjectDocNode(
                    project_id=project.id,
                    node_key=entity.key,
                    name=entity.name,
                    entity_type=entity.entity_type,
                    description=entity.description,
                )
            )

        for relation in relations:
            db.add(
                ProjectDocRelation(
                    project_id=project.id,
                    source_node_key=relation.source_key,
                    target_node_key=relation.target_key,
                    relation=relation.relation,
                    description=relation.description,
                )
            )

        for community_key, summary in community_summaries.items():
            db.add(
                ProjectDocCommunity(
                    project_id=project.id,
                    community_key=community_key,
                    summary=summary,
                )
            )

        db.flush()

    def _load_markdown_docs(self, project: Project) -> list[tuple[str, str]]:
        if not project.zip_file_url:
            return []

        zip_bytes = storage.read_bytes(project.zip_file_url)
        docs: list[tuple[str, str]] = []
        with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            for member in zf.infolist():
                if member.is_dir():
                    continue
                path_lower = member.filename.lower()
                if not path_lower.endswith((".md", ".markdown", ".mdx")):
                    continue
                content = zf.read(member).decode("utf-8", errors="ignore").strip()
                if content:
                    docs.append((member.filename, content))

        return docs

    def _chunk_text(self, text: str) -> Iterable[str]:
        cleaned = re.sub(r"\n{3,}", "\n\n", text).strip()
        if not cleaned:
            return []

        chunks = []
        start = 0
        while start < len(cleaned):
            end = min(len(cleaned), start + CHUNK_SIZE)
            chunks.append(cleaned[start:end])
            if end == len(cleaned):
                break
            start = max(0, end - CHUNK_OVERLAP)
        return chunks

    def _extract_from_chunk(self, chunk: str) -> tuple[list[EntityCandidate], list[RelationCandidate]]:
        if self._client:
            llm_output = self._llm_extract(chunk)
            entities, relations = self._parse_extraction(llm_output)
            if entities:
                return entities, relations

        return self._heuristic_extract(chunk)

    def _llm_extract(self, chunk: str) -> str:
        prompt = (
            "Extract entities and relationships from this documentation chunk. "
            "Use exact format lines.\n"
            "For each entity, output:\n"
            "entity_name: <name>\nentity_type: <type>\nentity_description: <description>\n"
            "For each relationship, output:\n"
            "source_entity: <name>\ntarget_entity: <name>\nrelation: <relation>\n"
            "relationship_description: <description>\n"
            "Chunk:\n"
            f"{chunk}"
        )
        response = self._client.responses.create(
            model=settings.OPENAI_MODEL_ID,
            input=prompt,
            temperature=0,
        )
        return response.output_text or ""

    def _parse_extraction(self, text: str) -> tuple[list[EntityCandidate], list[RelationCandidate]]:
        entities: list[EntityCandidate] = []
        relations: list[RelationCandidate] = []

        for name, entity_type, description in ENTITY_PATTERN.findall(text):
            norm_name = self._clean_field(name)
            if not norm_name:
                continue
            entities.append(
                EntityCandidate(
                    key=self._entity_key(norm_name),
                    name=norm_name,
                    entity_type=self._clean_field(entity_type) or "Concept",
                    description=self._clean_field(description),
                )
            )

        for source_name, target_name, relation, description in RELATION_PATTERN.findall(text):
            source_clean = self._clean_field(source_name)
            target_clean = self._clean_field(target_name)
            if not source_clean or not target_clean:
                continue
            relations.append(
                RelationCandidate(
                    source_key=self._entity_key(source_clean),
                    target_key=self._entity_key(target_clean),
                    relation=self._clean_field(relation) or "related_to",
                    description=self._clean_field(description),
                )
            )

        return entities, relations

    def _heuristic_extract(self, chunk: str) -> tuple[list[EntityCandidate], list[RelationCandidate]]:
        entities: dict[str, EntityCandidate] = {}

        for heading in re.findall(r"^#{1,6}\s+(.+)$", chunk, flags=re.MULTILINE):
            clean = self._clean_field(heading)
            if clean:
                key = self._entity_key(clean)
                entities[key] = EntityCandidate(key=key, name=clean, entity_type="Section", description="Documentation section")

        for token in re.findall(r"`([A-Za-z_][A-Za-z0-9_./-]{1,80})`", chunk):
            clean = self._clean_field(token)
            if clean:
                key = self._entity_key(clean)
                entities[key] = EntityCandidate(key=key, name=clean, entity_type="Symbol", description="Code or path symbol")

        relations: list[RelationCandidate] = []
        entity_keys = list(entities.keys())[:8]
        for source_key, target_key in combinations(entity_keys, 2):
            relations.append(
                RelationCandidate(
                    source_key=source_key,
                    target_key=target_key,
                    relation="co_occurs_in_chunk",
                    description="Both entities appear in the same documentation chunk",
                )
            )
            if len(relations) >= MAX_PAIRS_PER_CHUNK:
                break

        return list(entities.values()), relations

    def _build_communities(
        self,
        node_keys: Iterable[str],
        relations: list[RelationCandidate],
    ) -> dict[str, str]:
        adjacency: dict[str, set[str]] = {key: set() for key in node_keys}
        for relation in relations:
            adjacency.setdefault(relation.source_key, set()).add(relation.target_key)
            adjacency.setdefault(relation.target_key, set()).add(relation.source_key)

        community_of: dict[str, str] = {}
        visited = set()
        component_idx = 0

        for node in adjacency:
            if node in visited:
                continue
            stack = [node]
            component_nodes = []
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                component_nodes.append(current)
                stack.extend(adjacency[current] - visited)

            community_key = f"community_{component_idx}"
            for member in component_nodes:
                community_of[member] = community_key
            component_idx += 1

        return community_of

    def _summarize_communities(
        self,
        entities_map: dict[str, EntityCandidate],
        relations: list[RelationCandidate],
        community_map: dict[str, str],
    ) -> dict[str, str]:
        details_by_community: dict[str, list[str]] = defaultdict(list)

        for relation in relations:
            community_key = community_map.get(relation.source_key)
            if not community_key or community_map.get(relation.target_key) != community_key:
                continue
            source_name = entities_map[relation.source_key].name
            target_name = entities_map[relation.target_key].name
            details_by_community[community_key].append(
                f"{source_name} -> {target_name} -> {relation.relation} -> {relation.description}"
            )

        for key, entity in entities_map.items():
            community_key = community_map.get(key)
            if community_key and not details_by_community[community_key]:
                details_by_community[community_key].append(
                    f"{entity.name} -> isolated -> concept -> {entity.description}"
                )

        summaries: dict[str, str] = {}
        for community_key, details in details_by_community.items():
            details_text = "\n".join(details)
            summaries[community_key] = self._summarize_with_llm(details_text)

        return summaries

    def _summarize_with_llm(self, details_text: str) -> str:
        if not self._client:
            lines = details_text.splitlines()
            return " ".join(lines[:6])

        prompt = (
            "You are given graph relationship details. Summarize key entities and their relationships in 5-8 lines.\n"
            f"{details_text}"
        )
        response = self._client.responses.create(
            model=settings.OPENAI_MODEL_ID,
            input=prompt,
            temperature=0.2,
        )
        return (response.output_text or "").strip() or details_text[:1000]

    def _answer_from_summary(self, community_summary: str, query: str) -> str:
        if not self._client:
            return f"From one documentation community: {community_summary[:350]}"

        prompt = (
            "Use the community summary to answer the query. If uncertain, say so briefly.\n"
            f"Query: {query}\n"
            f"Community summary:\n{community_summary}"
        )
        response = self._client.responses.create(
            model=settings.OPENAI_MODEL_ID,
            input=prompt,
            temperature=0.2,
        )
        return (response.output_text or "").strip()

    def _answer_from_chunks(self, chunks: list[str], query: str) -> str:
        if not chunks:
            return ""

        chunk_context = "\n\n".join(chunks)
        if not self._client:
            return f"From documentation chunks: {chunk_context[:650]}"

        prompt = (
            "Answer using only the documentation chunks below. "
            "If the chunks are insufficient, explicitly state what is missing.\n"
            f"Query: {query}\n"
            f"Chunks:\n{chunk_context}"
        )
        response = self._client.responses.create(
            model=settings.OPENAI_MODEL_ID,
            input=prompt,
            temperature=0.2,
        )
        return (response.output_text or "").strip()

    def _aggregate_answers(self, answers: list[str], query: str) -> str:
        non_empty = [answer.strip() for answer in answers if answer and answer.strip()]
        if not non_empty:
            return "I could not derive an answer from the indexed documentation graph."

        if not self._client:
            merged = "\n".join(dict.fromkeys(non_empty))
            return f"Query: {query}\n{merged[:1200]}"

        prompt = (
            "Combine the following partial answers into a final concise answer grounded in project documentation. "
            "Do not invent facts."
        )
        response = self._client.responses.create(
            model=settings.OPENAI_MODEL_ID,
            input=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "query": query,
                            "partial_answers": non_empty,
                        }
                    ),
                },
            ],
            temperature=0.2,
        )
        final_text = (response.output_text or "").strip()
        return final_text or "\n".join(non_empty)

    @staticmethod
    def _entity_key(name: str) -> str:
        return re.sub(r"\s+", " ", name).strip().lower()

    @staticmethod
    def _clean_field(text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip().strip('"').strip("'")

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return set(re.findall(r"[a-zA-Z0-9_]+", (text or "").lower()))


graph_rag_service = GraphRAGService()
