import argparse
import json
import os
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

from app.core.config import settings
from app.core.storage import storage
from app.db.database import SessionLocal
from app.models.project import Project, ProjectDocCommunity, ProjectDocNode, ProjectDocRelation
from app.models.user import User
from app.services.graph_rag import GraphRAGService


def _to_json_file(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def _create_demo_zip() -> str:
    docs = {
        "docs/architecture.md": """
# Payment Platform Architecture

`GatewayService` receives API requests and forwards to `PaymentOrchestrator`.
`PaymentOrchestrator` calls `RiskEngine` before charging through `StripeAdapter`.
""",
        "docs/onboarding.md": """
# Merchant Onboarding

`MerchantService` creates merchant profiles and links them to `KYCWorkflow`.
`KYCWorkflow` uses `DocumentVerifier` and sends final status to `MerchantService`.
""",
        "docs/operations.md": """
# Incident Operations

`AlertManager` routes severe incidents to `OnCallRunbook`.
`OnCallRunbook` references `GatewayService` health checks and rollback actions.
""",
    }

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_name, content in docs.items():
            zf.writestr(file_name, content.strip() + "\n")

    return storage.save_bytes(buffer.getvalue(), extension="zip", content_type="application/zip")


def _ensure_api_key() -> None:
    env_key = os.getenv("OPENAI_API_KEY") or os.getenv("GENAILAB_API_KEY")
    if env_key and not settings.OPENAI_API_KEY:
        settings.OPENAI_API_KEY = env_key

    if not settings.OPENAI_API_KEY:
        raise RuntimeError("Missing OPENAI_API_KEY (or GENAILAB_API_KEY) for LLM-backed GraphRAG verification")


def run_graph_rag_verification(model_id: str, query: str, output_dir: Path, keep_data: bool) -> dict:
    settings.OPENAI_BASE_URL = "https://genailab.tcs.in/v1"
    settings.OPENAI_MODEL_ID = model_id
    _ensure_api_key()

    service = GraphRAGService()
    db = SessionLocal()
    created_user_id = None
    created_project_id = None
    zip_url = None

    try:
        # Step 1: source docs
        zip_url = _create_demo_zip()
        user = User(
            email=f"graphrag-verify-{datetime.utcnow().timestamp()}@example.com",
            full_name="GraphRAG Verifier",
            hashed_password="x",
        )
        db.add(user)
        db.flush()
        created_user_id = user.id

        project = Project(
            user_id=user.id,
            name="GraphRAG Verification Project",
            description="Synthetic project for step-by-step GraphRAG validation",
            source_type="zip",
            zip_file_url=zip_url,
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        created_project_id = project.id

        docs = service._load_markdown_docs(project)
        _to_json_file(
            output_dir / "step_1_source_docs.json",
            {
                "project_id": project.id,
                "zip_file_url": zip_url,
                "doc_count": len(docs),
                "documents": [{"path": path, "preview": text[:400]} for path, text in docs],
            },
        )

        # Step 2: chunks
        chunk_records = []
        for path, text in docs:
            chunks = list(service._chunk_text(text))
            for idx, chunk in enumerate(chunks):
                chunk_records.append(
                    {
                        "doc_path": path,
                        "chunk_index": idx,
                        "length": len(chunk),
                        "text": chunk,
                    }
                )
        _to_json_file(
            output_dir / "step_2_chunks.json",
            {
                "chunk_count": len(chunk_records),
                "chunks": chunk_records,
            },
        )

        # Step 3: extraction
        extraction_records = []
        for chunk in chunk_records:
            llm_raw = service._llm_extract(chunk["text"])
            entities, relations = service._parse_extraction(llm_raw)
            extraction_records.append(
                {
                    "doc_path": chunk["doc_path"],
                    "chunk_index": chunk["chunk_index"],
                    "raw_output": llm_raw,
                    "parsed_entities": [e.__dict__ for e in entities],
                    "parsed_relations": [r.__dict__ for r in relations],
                }
            )
        _to_json_file(
            output_dir / "step_3_extraction.json",
            {
                "records": extraction_records,
            },
        )

        # Step 4 + 5: graph + community summaries via persisted index build
        counts = service.build_index(db, project)
        nodes = db.query(ProjectDocNode).filter(ProjectDocNode.project_id == project.id).all()
        relations = db.query(ProjectDocRelation).filter(ProjectDocRelation.project_id == project.id).all()
        communities = db.query(ProjectDocCommunity).filter(ProjectDocCommunity.project_id == project.id).all()

        _to_json_file(
            output_dir / "step_4_graph_elements.json",
            {
                "counts": {
                    "nodes": counts[0],
                    "relations": counts[1],
                    "communities": counts[2],
                },
                "nodes": [
                    {
                        "node_key": n.node_key,
                        "name": n.name,
                        "entity_type": n.entity_type,
                        "description": n.description,
                    }
                    for n in nodes
                ],
                "relations": [
                    {
                        "source_node_key": r.source_node_key,
                        "target_node_key": r.target_node_key,
                        "relation": r.relation,
                        "description": r.description,
                    }
                    for r in relations
                ],
            },
        )

        _to_json_file(
            output_dir / "step_5_community_summaries.json",
            {
                "communities": [
                    {
                        "community_key": c.community_key,
                        "summary": c.summary,
                    }
                    for c in communities
                ]
            },
        )

        # Step 6: query and final answer
        answer = service.answer_query(db, project, query)
        _to_json_file(
            output_dir / "step_6_query_answer.json",
            {
                "query": query,
                "answer": answer,
            },
        )

        report = {
            "project_id": project.id,
            "model_id": settings.OPENAI_MODEL_ID,
            "base_url": settings.OPENAI_BASE_URL,
            "artifacts_dir": str(output_dir),
            "step_counts": {
                "documents": len(docs),
                "chunks": len(chunk_records),
                "nodes": counts[0],
                "relations": counts[1],
                "communities": counts[2],
            },
            "query": query,
            "answer_preview": answer[:400],
        }
        _to_json_file(output_dir / "verification_report.json", report)
        return report
    finally:
        if not keep_data and created_project_id:
            db.query(ProjectDocRelation).filter(ProjectDocRelation.project_id == created_project_id).delete()
            db.query(ProjectDocNode).filter(ProjectDocNode.project_id == created_project_id).delete()
            db.query(ProjectDocCommunity).filter(ProjectDocCommunity.project_id == created_project_id).delete()
            db.query(Project).filter(Project.id == created_project_id).delete()
        if not keep_data and created_user_id:
            db.query(User).filter(User.id == created_user_id).delete()
        db.commit()
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run step-by-step GraphRAG verification and save artifacts")
    parser.add_argument("--model", default="azure/genailab-maas-gpt-4o-mini", help="LLM model ID")
    parser.add_argument(
        "--query",
        default="How does the payment architecture connect gateway, risk, and charge execution?",
        help="Validation query for final answer generation",
    )
    parser.add_argument(
        "--output-dir",
        default="uploads/graphrag_verification",
        help="Directory where step JSON artifacts will be written",
    )
    parser.add_argument("--keep-data", action="store_true", help="Keep created DB rows after test")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    report = run_graph_rag_verification(
        model_id=args.model,
        query=args.query,
        output_dir=output_dir,
        keep_data=args.keep_data,
    )
    print(json.dumps(report, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()