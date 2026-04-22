# FastAPI Auth & AI Chat API

A production-ready, scalable REST API built with **FastAPI**, **SQLAlchemy**, and **Alembic**, utilizing **uv** for lightning-fast package management. This project implements secure user authentication (via JWT tokens), a fully persistent AI Chatbot (via Server-Sent Events / SSE) with session management, and robust File Upload handling (Local Disk or S3).

## Features

- **FastAPI**: Modern, fast web framework for building APIs.
- **SQLAlchemy (ORM)**: Clean database interactions and modeling.
- **Alembic**: Robust database migration management.
- **Bcrypt & PyJWT**: Secure password hashing and token-based authentication.
- **SSE Streaming (sse-starlette)**: Real-time, word-by-word streaming of AI responses.
- **Agno Agent**: Agentic LLM integration generating seamless conversational AI.
- **Chat Persistence**: Full history tracking with nested "Chat Sessions", "Messages", and attached files securely locked to individual users.
- **Unified Storage Engine**: Seamlessly switch between Local File Storage and Cloud S3 (AWS, GCP, Localstack) using `boto3`.

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
│   │   ├── security.py     # JWT & Hashing logic
│   │   └── storage.py      # Local disk / S3 bucket upload manager
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

# Storage Settings (Local or S3)
STORAGE_PROVIDER="local"  # change to "s3" to use boto3
S3_BUCKET_NAME="my-ai-bucket"
AWS_ACCESS_KEY_ID="xxx"
AWS_SECRET_ACCESS_KEY="xxx"
AWS_REGION="us-east-1"
# AWS_ENDPOINT_URL="http://localhost:4566" # Optional: for Docker/Localstack GCP/AWS emulation
```

**3. Install Dependencies with `uv`**
```bash
uv sync
```

## Database Migrations (Alembic)

The application uses Alembic to manage database schema updates. 

```bash
uv run alembic revision --autogenerate -m "Describe your changes here"
uv run alembic upgrade head
```

## Running the Server

Start the development server using **uvicorn**:

```bash
uv run uvicorn app.main:app --reload
```
By default, the API will be available at `http://127.0.0.1:8000`.

## API Documentation

- **Swagger UI**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc**: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

## Frontend Workflow for File Uploads & Chat

To implement a ChatGPT-like file attachment flow in your frontend API client, follow this 2-step process:

1. **Step 1: Upload the Files (Multipart Form Data)**
   - When the user drags & drops files, send them via POST to `/api/v1/chat/batch_upload`.
   - The server will upload them to `STORAGE_PROVIDER` (Local or S3) and respond with an array of URLs.
   - Example Response: `{"file_urls": ["/uploads/random-uuid.pdf", "/uploads/random-uuid.png"]}`

2. **Step 2: Stream the Message with Attached Files**
   - When the user types their prompt and hits "Send", trigger the SSE stream endpoint.
   - Send the prompt and the URLs you received from Step 1 in the JSON body to `POST /api/v1/chat/{chat_id}/stream`.
   - Example Body:
     ```json
     {
       "message": "Summarize these documents",
       "file_urls": ["/uploads/random-uuid.pdf", "/uploads/random-uuid.png"]
     }
     ```
   - The backend will successfully link those files to the `ChatMessage` database row and feed the file context into the AI model's prompt natively.

## Endpoints Summary

### Authentication
- `POST /api/v1/auth/signup`: Create a new user.
- `POST /api/v1/auth/login`: Authenticate and receive a JWT Bearer `access_token`.
- `GET /api/v1/auth/me`: Retrieve current logged-in user securely.

### Chat & Streaming (Requires Authorization Token)
- `POST /api/v1/chat/`: Create a new, empty chat session.
- `GET /api/v1/chat/`: List all past chat sessions.
- `GET /api/v1/chat/{chat_id}`: Load full message history (includes `file_urls` array on messages).
- `POST /api/v1/chat/batch_upload`: Accepts multiple files, uploads them, and returns an array of public URLs.
- `POST /api/v1/chat/{chat_id}/stream`: Real-time SSE streaming endpoint. Expects `message` and optionally `file_urls`.
