from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.database import Base


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    source_type = Column(String, nullable=True)  # "zip" or "github"
    repository_url = Column(String, nullable=True)
    zip_file_url = Column(String, nullable=True)
    docs_index_status = Column(String, nullable=False, default="not_indexed")
    docs_index_error = Column(Text, nullable=True)
    docs_indexed_at = Column(DateTime(timezone=True), nullable=True)
    docs_nodes_count = Column(Integer, nullable=False, default=0)
    docs_relations_count = Column(Integer, nullable=False, default=0)
    docs_communities_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="projects")
    chats = relationship("ProjectChat", back_populates="project", cascade="all, delete-orphan")


class ProjectChat(Base):
    __tablename__ = "project_chats"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    title = Column(String, default="New Project Chat")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    project = relationship("Project", back_populates="chats")
    messages = relationship("ProjectChatMessage", back_populates="chat", cascade="all, delete-orphan")


class ProjectChatMessage(Base):
    __tablename__ = "project_chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey("project_chats.id"), nullable=False, index=True)
    role = Column(String, nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    chat = relationship("ProjectChat", back_populates="messages")


class ProjectDocNode(Base):
    __tablename__ = "project_doc_nodes"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    node_key = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    description = Column(Text, nullable=True)


class ProjectDocRelation(Base):
    __tablename__ = "project_doc_relations"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    source_node_key = Column(String, nullable=False, index=True)
    target_node_key = Column(String, nullable=False, index=True)
    relation = Column(String, nullable=False)
    description = Column(Text, nullable=True)


class ProjectDocCommunity(Base):
    __tablename__ = "project_doc_communities"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    community_key = Column(String, nullable=False, index=True)
    summary = Column(Text, nullable=False)
