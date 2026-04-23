import json
from typing import AsyncGenerator, List

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_current_user
from app.core.storage import storage
from app.db.database import get_db
from app.models.chat import ChatMessage, ChatSession
from app.models.user import User as UserModel
from app.models.project import Project
from app.services.graph_rag import graph_rag_service
from app.schemas.chat import ChatRequest, ChatSessionListResponse, ChatSessionResponse

router = APIRouter()


def _get_owned_chat(db: Session, chat_id: int, user_id: int) -> ChatSession:
	chat = db.query(ChatSession).filter(ChatSession.id == chat_id, ChatSession.user_id == user_id).first()
	if not chat:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")
	return chat


@router.post("/", response_model=ChatSessionResponse)
def create_chat(db: Session = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
	new_chat = ChatSession(user_id=current_user.id, title="New Chat")
	db.add(new_chat)
	db.commit()
	db.refresh(new_chat)
	return new_chat


@router.get("/", response_model=List[ChatSessionListResponse])
def get_chats(db: Session = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
	return db.query(ChatSession).filter(ChatSession.user_id == current_user.id).order_by(ChatSession.created_at.desc()).all()


@router.get("/{chat_id}", response_model=ChatSessionResponse)
def get_chat(chat_id: int, db: Session = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
	return _get_owned_chat(db, chat_id, current_user.id)


async def dummy_sse_stream(
	request: Request,
	db: Session,
	chat: ChatSession,
	message: str,
	file_urls: List[str],
	project: Project | None = None,
) -> AsyncGenerator[dict, None]:
	user_msg = ChatMessage(session_id=chat.id, role="user", content=message, file_urls=file_urls)
	db.add(user_msg)

	if project:
		# If project provided, try to answer using project documentation (graph + semantic chunks)
		if project.docs_index_status != "ready":
			if not project.zip_file_url:
				reply = (
					"I cannot answer from documentation yet because this project has no source ZIP attached. "
					"Upload a ZIP or GitHub URL, preprocess the project, then ask again."
				)
			else:
				try:
					project.docs_index_status = "indexing"
					project.docs_index_error = None
					db.add(project)
					db.commit()
					db.refresh(project)
					graph_rag_service.build_index(db, project)
				except Exception as exc:  # noqa: BLE001
					db.rollback()
					project.docs_index_status = "failed"
					project.docs_index_error = str(exc)
					db.add(project)
					db.commit()
					reply = (
						"I tried to build the project documentation graph but it failed. "
						f"Reason: {exc}"
					)
				else:
					reply = graph_rag_service.answer_query(db, project, message)
		else:
			reply = graph_rag_service.answer_query(db, project, message)

		assistant_msg = ChatMessage(session_id=chat.id, role="assistant", content=reply)
		db.add(assistant_msg)
	else:
		dummy_response = f"[dummy] I received your message: {message}"
		if file_urls:
			dummy_response += f" (with {len(file_urls)} attached file(s))"

		assistant_msg = ChatMessage(session_id=chat.id, role="assistant", content=dummy_response)
		db.add(assistant_msg)

	if chat.title == "New Chat":
		chat.title = message[:40] + "..." if len(message) > 40 else message

	db.commit()

	output_text = assistant_msg.content
	for token in output_text.split(" "):
		if await request.is_disconnected():
			break
		yield {"event": "message", "data": json.dumps({"chunk": token + " "})}

	yield {"event": "message", "data": "[DONE]"}


@router.post("/{chat_id}/stream", summary="Dummy stream response into a specific chat session")
async def chat_stream(
	chat_id: int,
	request: Request,
	chat_in: ChatRequest,
	db: Session = Depends(get_db),
	current_user: UserModel = Depends(get_current_user),
):
	chat = _get_owned_chat(db, chat_id, current_user.id)
	file_urls = chat_in.file_urls or []
	project_obj: Project | None = None
	if getattr(chat_in, "project_id", None):
		project_obj = db.query(Project).filter(Project.id == chat_in.project_id, Project.user_id == current_user.id).first()
		if not project_obj:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

	return EventSourceResponse(
		dummy_sse_stream(
			request=request,
			db=db,
			chat=chat,
			message=chat_in.message,
			file_urls=file_urls,
			project=project_obj,
		),
		ping=15,
	)


@router.post("/batch_upload", summary="Bulk upload multiple files")
def batch_upload_files(
	files: List[UploadFile] = File(...),
	current_user: UserModel = Depends(get_current_user),
):
	uploaded_urls = []

	for file in files:
		final_file_url = storage.save_file(file)
		uploaded_urls.append(final_file_url)

	return {
		"status": "success",
		"file_urls": uploaded_urls,
		"message": f"Successfully uploaded {len(files)} files",
	}
