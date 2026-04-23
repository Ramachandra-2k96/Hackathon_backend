import json
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.storage import storage
from app.db.database import get_db
from app.models.project import Project, ProjectChat, ProjectChatMessage
from app.models.user import User as UserModel
from app.schemas.project import (
    PreprocessResponse,
    ProjectChatCreate,
    ProjectChatMessageCreate,
    ProjectChatMessageResponse,
    ProjectChatResponse,
    ProjectChatSendResponse,
    ProjectResponse,
    ProjectUpdate,
)

router = APIRouter()


def _normalize_github_repo_url(repo_url: str) -> tuple[str, str, str | None]:
    parsed = urlparse(repo_url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Repository URL must be HTTP/HTTPS")
    if parsed.netloc.lower() != "github.com":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only public GitHub repository URLs are supported")

    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid GitHub repository URL")

    owner = parts[0]
    repo = parts[1].replace(".git", "")
    branch = None
    if len(parts) >= 4 and parts[2] == "tree":
        branch = "/".join(parts[3:])

    normalized = f"https://github.com/{owner}/{repo}"
    return normalized, owner, branch


def _get_default_branch(owner: str, repo: str) -> str:
    api_url = f"https://api.github.com/repos/{owner}/{repo}"
    request = Request(api_url, headers={"Accept": "application/vnd.github+json", "User-Agent": "hackathon-backend"})
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not read GitHub repository metadata: {exc}",
        ) from exc

    default_branch = payload.get("default_branch")
    if not default_branch:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not determine default branch")
    return default_branch


def _download_public_github_zip(owner: str, repo: str, branch: str) -> bytes:
    zip_url = f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{branch}"
    request = Request(zip_url, headers={"User-Agent": "hackathon-backend"})
    try:
        with urlopen(request, timeout=60) as response:
            return response.read()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to download repository zip: {exc}",
        ) from exc


def _resolve_project_source(repository_url: str | None, zip_file: UploadFile | None) -> tuple[str, str | None, str]:
    if zip_file:
        if not zip_file.filename or not zip_file.filename.lower().endswith(".zip"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file must be a .zip")
        zip_file_url = storage.save_file(zip_file)
        return "zip", None, zip_file_url

    normalized_repo_url, owner, explicit_branch = _normalize_github_repo_url(repository_url or "")
    repo = normalized_repo_url.rsplit("/", 1)[-1]
    branch = explicit_branch or _get_default_branch(owner, repo)
    zip_bytes = _download_public_github_zip(owner, repo, branch)
    zip_file_url = storage.save_bytes(zip_bytes, extension="zip", content_type="application/zip")
    return "github", normalized_repo_url, zip_file_url


def _get_owned_project(db: Session, project_id: int, user_id: int) -> Project:
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == user_id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def _get_owned_chat(db: Session, project_id: int, chat_id: int, user_id: int) -> ProjectChat:
    chat = (
        db.query(ProjectChat)
        .join(Project, Project.id == ProjectChat.project_id)
        .filter(ProjectChat.id == chat_id, ProjectChat.project_id == project_id, Project.user_id == user_id)
        .first()
    )
    if not chat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project chat not found")
    return chat


@router.post("/", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    name: str = Form(...),
    description: str | None = Form(None),
    repository_url: str | None = Form(None),
    zip_file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    has_repo = bool(repository_url and repository_url.strip())
    has_zip = zip_file is not None
    if has_repo and has_zip:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide only one source: repository_url or zip_file",
        )

    if has_repo or has_zip:
        source_type, normalized_repo_url, zip_file_url = _resolve_project_source(repository_url, zip_file)
    else:
        source_type = None
        normalized_repo_url = None
        zip_file_url = None

    project = Project(
        user_id=current_user.id,
        name=name,
        description=description,
        source_type=source_type,
        repository_url=normalized_repo_url,
        zip_file_url=zip_file_url,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.put("/{project_id}/source", response_model=ProjectResponse)
def set_project_source(
    project_id: int,
    repository_url: str | None = Form(None),
    zip_file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    has_repo = bool(repository_url and repository_url.strip())
    has_zip = zip_file is not None
    if has_repo == has_zip:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide exactly one source: either repository_url or zip_file",
        )

    project = _get_owned_project(db, project_id, current_user.id)
    source_type, normalized_repo_url, zip_file_url = _resolve_project_source(repository_url, zip_file)

    project.source_type = source_type
    project.repository_url = normalized_repo_url
    project.zip_file_url = zip_file_url

    db.commit()
    db.refresh(project)
    return project


@router.get("/", response_model=list[ProjectResponse])
def list_projects(
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    return db.query(Project).filter(Project.user_id == current_user.id).order_by(Project.created_at.desc()).all()


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    return _get_owned_project(db, project_id, current_user.id)


@router.put("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    project = _get_owned_project(db, project_id, current_user.id)

    if payload.name is not None:
        project.name = payload.name
    if payload.description is not None:
        project.description = payload.description

    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    project = _get_owned_project(db, project_id, current_user.id)
    db.delete(project)
    db.commit()


@router.post("/{project_id}/preprocess", response_model=PreprocessResponse)
def preprocess_project_docs(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    project = _get_owned_project(db, project_id, current_user.id)
    return PreprocessResponse(
        project_id=project.id,
        status="queued",
        detail="Dummy preprocessing endpoint currently does nothing.",
    )


@router.post("/{project_id}/chats", response_model=ProjectChatResponse, status_code=status.HTTP_201_CREATED)
def create_project_chat(
    project_id: int,
    payload: ProjectChatCreate,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current_user.id)
    chat = ProjectChat(project_id=project_id, title=payload.title or "New Project Chat")
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return chat


@router.get("/{project_id}/chats", response_model=list[ProjectChatResponse])
def list_project_chats(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current_user.id)
    return db.query(ProjectChat).filter(ProjectChat.project_id == project_id).order_by(ProjectChat.created_at.desc()).all()


@router.delete("/{project_id}/chats/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_chat(
    project_id: int,
    chat_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    chat = _get_owned_chat(db, project_id, chat_id, current_user.id)
    db.delete(chat)
    db.commit()


@router.get("/{project_id}/chats/{chat_id}/messages", response_model=list[ProjectChatMessageResponse])
def list_project_chat_messages(
    project_id: int,
    chat_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    _get_owned_chat(db, project_id, chat_id, current_user.id)
    return db.query(ProjectChatMessage).filter(ProjectChatMessage.chat_id == chat_id).order_by(ProjectChatMessage.created_at.asc()).all()


@router.post("/{project_id}/chats/{chat_id}/messages", response_model=ProjectChatSendResponse)
def send_dummy_project_chat_message(
    project_id: int,
    chat_id: int,
    payload: ProjectChatMessageCreate,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    chat = _get_owned_chat(db, project_id, chat_id, current_user.id)

    user_message = ProjectChatMessage(chat_id=chat.id, role="user", content=payload.message)
    db.add(user_message)
    db.flush()

    dummy_reply_text = f"[dummy] Received your message for project chat {chat.id}: {payload.message}"
    assistant_message = ProjectChatMessage(chat_id=chat.id, role="assistant", content=dummy_reply_text)
    db.add(assistant_message)

    if chat.title == "New Project Chat":
        chat.title = payload.message[:40] + ("..." if len(payload.message) > 40 else "")

    db.commit()
    db.refresh(user_message)
    db.refresh(assistant_message)

    return ProjectChatSendResponse(user_message=user_message, assistant_message=assistant_message)
