from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None


class ProjectResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    source_type: Optional[str]
    repository_url: Optional[str]
    zip_file_url: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class PreprocessResponse(BaseModel):
    project_id: int
    status: str
    detail: str


class ProjectChatCreate(BaseModel):
    title: Optional[str] = Field(default="New Project Chat", min_length=1, max_length=200)


class ProjectChatResponse(BaseModel):
    id: int
    project_id: int
    title: str
    created_at: datetime

    class Config:
        from_attributes = True


class ProjectChatMessageCreate(BaseModel):
    message: str = Field(..., min_length=1)


class ProjectChatMessageResponse(BaseModel):
    id: int
    chat_id: int
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class ProjectChatSendResponse(BaseModel):
    user_message: ProjectChatMessageResponse
    assistant_message: ProjectChatMessageResponse
