from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="The message sent by the user to the AI chatbot")

class ChatResponseChunk(BaseModel):
    chunk: str = Field(..., description="A chunk of text from the AI streaming response")
