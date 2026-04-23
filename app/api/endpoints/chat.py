import json
from typing import List, AsyncGenerator
from fastapi import APIRouter, Depends, Request, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.core.config import settings

from app.db.database import get_db
from app.api.deps import get_current_user
from app.models.user import User as UserModel
from app.models.chat import ChatSession, ChatMessage
from app.schemas.chat import ChatRequest, ChatSessionResponse, ChatSessionListResponse
from app.core.storage import storage

# Note: Keeping your chosen Agent logic from agno
from agno.agent import Agent
from agno.models.openai import OpenAI

router = APIRouter()

# Global agent initialization just as you configured it
agent = Agent(
    model=OpenAI(
        id=settings.OPENAI_MODEL_ID,
        api_key=settings.OPENAI_API_KEY,
    ),
    markdown=True,
)

@router.post("/", response_model=ChatSessionResponse)
def create_chat(db: Session = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
    """
    Create a fresh empty chat session.
    """
    new_chat = ChatSession(user_id=current_user.id, title="New Chat")
    db.add(new_chat)
    db.commit()
    db.refresh(new_chat)
    return new_chat

@router.get("/", response_model=List[ChatSessionListResponse])
def get_chats(db: Session = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
    """
    Load all prior chat sessions for the active user.
    """
    return db.query(ChatSession).filter(ChatSession.user_id == current_user.id).order_by(ChatSession.created_at.desc()).all()

@router.get("/{chat_id}", response_model=ChatSessionResponse)
def get_chat(chat_id: int, db: Session = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
    """
    Load a strictly specific chat's history.
    """
    chat = db.query(ChatSession).filter(ChatSession.id == chat_id, ChatSession.user_id == current_user.id).first()
    if not chat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")
    return chat

async def agent_sse_stream(
    request: Request,
    db: Session,
    chat_id: int,
    message: str,
    file_urls: List[str],
    user_name: str
) -> AsyncGenerator[dict, None]:
    """
    Streams the SSE response while persisting user and AI messages faithfully into exactly matching DB columns.
    """
    # 1. Immediate DB Persistence - Save user prompt to exact chat session
    user_msg = ChatMessage(session_id=chat_id, role="user", content=message, file_urls=file_urls)
    db.add(user_msg)
    db.commit()

    accumulated_content = ""
    
    # Pre-process message for the AI: if files exist, let the AI know
    prompt = f"User {user_name} says: {message}"
    if file_urls:
        prompt += f"\n[The user has attached the following files: {', '.join(file_urls)}]"

    # 2. Iterate dynamically as the AI generates tokens natively
    async for event in agent.arun(prompt, stream=True):
        if await request.is_disconnected():
            break
        if getattr(event, "content", None):
            accumulated_content += event.content
            yield {"event": "message", "data": json.dumps({"chunk": event.content})}

    # 3. Post-Stream Persistence - Ensure AI string chunk memory is merged and saved locally
    if accumulated_content:
        ai_msg = ChatMessage(session_id=chat_id, role="assistant", content=accumulated_content)
        db.add(ai_msg)
        
        # Smart UI Polish: Retitle the chat natively based on the first message sent
        session = db.query(ChatSession).filter(ChatSession.id == chat_id).first()
        if session and session.title == "New Chat":
            session.title = message[:40] + "..." if len(message) > 40 else message
            
        db.commit()

    # 4. Standard AI paradigm: send a [DONE] signal to tell client generations has finished
    yield {"event": "message", "data": "[DONE]"}


@router.post("/{chat_id}/stream", summary="Stream AI Chat via SSE into a specific Chat Session")
async def chat_stream(
    chat_id: int,
    request: Request,
    chat_in: ChatRequest,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    """
    Stream message logic directly into an active chat DB row.
    """
    # Authorization & validations to ensure user owns this chat ID session
    chat = db.query(ChatSession).filter(ChatSession.id == chat_id, ChatSession.user_id == current_user.id).first()
    if not chat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")

    return EventSourceResponse(
        agent_sse_stream(
            request=request,
            db=db,
            chat_id=chat.id,
            message=chat_in.message,
            file_urls=chat_in.file_urls,
            user_name=current_user.full_name or current_user.email
        ),
        ping=15
    )

@router.post("/batch_upload", summary="Bulk Upload Multiple Files (Returns URLs to include in ChatRequest)")
def batch_upload_files(
    files: List[UploadFile] = File(...),
    current_user: UserModel = Depends(get_current_user)
):
    """
    Handles robust multi-file uploads. Use this endpoint BEFORE sending the stream request.
    It returns a list of URLs that the frontend can attach inside `ChatRequest.file_urls`.
    """
    uploaded_urls = []
    
    for file in files:
        # The StorageManager automatically checks .env (STORAGE_PROVIDER) to decide if local or S3 boto3 
        final_file_url = storage.save_file(file)
        uploaded_urls.append(final_file_url)

    return {
        "status": "success", 
        "file_urls": uploaded_urls,
        "message": f"Successfully uploaded {len(files)} files to {settings.STORAGE_PROVIDER}"
    }
