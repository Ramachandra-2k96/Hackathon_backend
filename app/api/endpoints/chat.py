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
) -> AsyncGenerator[dict, None]:
	user_msg = ChatMessage(session_id=chat.id, role="user", content=message, file_urls=file_urls)
	db.add(user_msg)

	dummy_response = f"[dummy] I received your message: {message}"
	if file_urls:
		dummy_response += f" (with {len(file_urls)} attached file(s))"

	assistant_msg = ChatMessage(session_id=chat.id, role="assistant", content=dummy_response)
	db.add(assistant_msg)

	if chat.title == "New Chat":
		chat.title = message[:40] + "..." if len(message) > 40 else message

	db.commit()

	for token in dummy_response.split(" "):
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
	return EventSourceResponse(
		dummy_sse_stream(
			request=request,
			db=db,
			chat=chat,
			message=chat_in.message,
			file_urls=file_urls,
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
