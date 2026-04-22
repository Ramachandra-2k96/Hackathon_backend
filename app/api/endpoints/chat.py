import json
from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse
from agno.agent import Agent
from agno.models.openai.like import OpenAILike
from app.schemas.chat import ChatRequest
from app.api.deps import get_current_user
from app.models.user import User as UserModel

router = APIRouter()

agent = Agent(
    model=OpenAILike(
        id="your-model-id",
        api_key="YOUR_API_KEY",
        base_url="https://your-provider.com/v1",  # custom LLM source
    ),
    markdown=True,
)

async def agent_sse_stream(request: Request, message: str, user_name: str):
    # agent.arun(..., stream=True) returns an async iterator of RunOutputEvent
    async for event in agent.arun(
        f"User {user_name} says: {message}", stream=True
    ):
        if await request.is_disconnected():
            break
        if getattr(event, "content", None):
            yield {"event": "message", "data": json.dumps({"chunk": event.content})}

    yield {"event": "message", "data": "[DONE]"}

@router.post("/stream", summary="Stream AI Chat via SSE")
async def chat_stream(
    request: Request,
    chat_in: ChatRequest,
    current_user: UserModel = Depends(get_current_user),
):
    return EventSourceResponse(
        agent_sse_stream(
            request,
            chat_in.message,
            user_name=current_user.full_name or current_user.email,
        ),
        ping=15,
    )