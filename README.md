# FastAPI Auth & AI Chat API

A production-ready, scalable REST API built with **FastAPI**, **SQLAlchemy**, and **Alembic**, utilizing **uv** for lightning-fast package management. This project implements secure user authentication (via JWT tokens) and a fully persistent AI Chatbot (via Server-Sent Events / SSE) complete with chat session management and message history using the **Agno** AI agent framework.

## Features

- **FastAPI**: Modern, fast web framework for building APIs.
- **SQLAlchemy (ORM)**: Clean database interactions and modeling.
- **Alembic**: Robust database migration management.
- **Bcrypt & PyJWT**: Secure password hashing and token-based authentication.
- **SSE Streaming (sse-starlette)**: Real-time, word-by-word streaming of AI responses.
- **Agno Agent**: Agentic LLM integration (OpenAI-compatible) generating seamless conversational AI.
- **Chat Persistence**: Full history tracking with nested "Chat Sessions" and "Messages", securely locked to individual users.

## Prerequisites

- [uv](https://github.com/astral-sh/uv) installed on your system.
- Python 3.11+ (managed by `uv`).

## Project Structure

```text
├── app/
│   ├── api/
│   │   ├── endpoints/
│   │   │   ├── auth.py     # Auth routes (Signup, Login, Me)
│   │   │   └── chat.py     # AI Chat routes & SSE Streaming logic
│   │   ├── deps.py         # Dependencies (like get_current_user)
│   ├── core/
│   │   ├── config.py       # Pydantic Settings base
│   │   └── security.py     # JWT & Hashing logic
│   ├── db/
│   │   └── database.py     # SQLAlchemy Engine & Session
│   ├── models/
│   │   ├── user.py         # User DB Schema
│   │   └── chat.py         # ChatSession and ChatMessage Schemas
│   ├── schemas/
│   │   ├── user.py         # Pydantic Models for user validation
│   │   └── chat.py         # Pydantic Models for chat validation
│   └── main.py             # FastAPI App Entrypoint
├── alembic/                # DB Migrations folder
├── .env                    # Environment variables
├── alembic.ini             # Alembic configuration
└── pyproject.toml          # Project metadata and dependencies
```

## Setup & Installation

**1. Clone the repository and navigate to the directory**
```bash
cd backend
```

**2. Configure your environment**
Ensure your `.env` file is populated securely. An example of `.env`:
```env
PROJECT_NAME="Auth & AI Chat API"
SECRET_KEY="your-super-secret-key-change-me"
ALGORITHM="HS256"
ACCESS_TOKEN_EXPIRE_MINUTES=30
SQLALCHEMY_DATABASE_URI="sqlite:///./app.db"
# Note: You must also configure your Agno agent's API keys directly inside chat.py or link them here!
```

**3. Install Dependencies with `uv`**
```bash
uv sync
```
*Note: `uv` transparently creates a `.venv` virtual environment and installs configurations securely.*

## Database Migrations (Alembic)

The application uses Alembic to manage database schema updates. 

**Generate a new migration (after modifying `app/models/`):**
```bash
uv run alembic revision --autogenerate -m "Describe your changes here"
```

**Apply migrations to the database (Creates tables / updates schema):**
```bash
uv run alembic upgrade head
```

**Undo the last migration (Downgrade):**
```bash
uv run alembic downgrade -1
```

**Reset the database entirely (Downgrade to base):**
```bash
uv run alembic downgrade base
```

## Running the Server

Start the development server using **uvicorn**:

```bash
uv run uvicorn app.main:app --reload
```
By default, the API will be available at `http://127.0.0.1:8000`.

## API Documentation

FastAPI natively supports auto-generated, interactive API documentation. While the server is running, visit:
- **Swagger UI**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc**: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

## Endpoints

### Authentication
- `POST /api/v1/auth/signup`: Create a new user with `email`, `password`, and `full_name`.
- `POST /api/v1/auth/login`: Authenticate and receive a JWT Bearer `access_token`.
- `GET /api/v1/auth/me`: Retrieve current logged-in user securely (requires `Authorization: Bearer <token>`).

### Chat & Streaming (Requires Authorization Token)
- `POST /api/v1/chat/`: Create a new, empty chat session (Returns `chat_id`).
- `GET /api/v1/chat/`: List all past chat sessions for the authenticated user (Dashboard sidebar feature).
- `GET /api/v1/chat/{chat_id}`: Load the full history of messages for a specific chat.
- `POST /api/v1/chat/{chat_id}/stream`: Real-time Server-Sent Events (SSE) AI response stream. Automatically saves both the user's prompt and the AI's generated response to the database upon completion.
