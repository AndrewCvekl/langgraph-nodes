"""FastAPI server for the Music Store Support Bot.

Serves:
- /api/* JSON endpoints to invoke/resume the LangGraph app graph
- / (and other paths) static frontend build from the Vite UI bundle
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from app.config import config
from app.graphs.app_graph import compile_app_graph


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    thread_id: Optional[str] = None
    user_id: Optional[int] = None


class ResumeRequest(BaseModel):
    thread_id: str = Field(..., min_length=1)
    resume: str


class ChatResponse(BaseModel):
    thread_id: str
    assistant_messages: list[dict] = Field(default_factory=list)
    interrupt: Optional[dict] = None


def _extract_interrupt_payload(result: dict) -> Optional[dict]:
    """Return the first interrupt payload as a JSON-serializable dict (or None)."""
    interrupts = result.get("__interrupt__")
    if not interrupts:
        return None
    first = interrupts[0]
    # Some LangGraph interrupt objects expose a `.value` attribute.
    payload = first.value if hasattr(first, "value") else first
    if isinstance(payload, dict):
        return payload
    # Last resort: wrap non-dict payloads
    return {"type": "unknown", "value": payload}


def _safe_assistant_messages(result: dict) -> list[dict]:
    msgs = result.get("assistant_messages") or []
    if isinstance(msgs, list):
        # Ensure JSON-serializable dicts
        safe: list[dict] = []
        for m in msgs:
            if isinstance(m, dict):
                safe.append(m)
        return safe
    return []


# Compile graph once for the server process.
GRAPH = compile_app_graph()


app = FastAPI(title="Music Store Support Bot", version="0.1.0")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    thread_id = req.thread_id or str(uuid.uuid4())
    user_id = req.user_id if req.user_id is not None else config.DEFAULT_USER_ID

    invoke_config = {"configurable": {"thread_id": thread_id}}
    input_state = {
        "messages": [HumanMessage(content=req.message)],
        "user_id": user_id,
    }

    try:
        result = GRAPH.invoke(input_state, invoke_config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Graph error: {e}")

    return ChatResponse(
        thread_id=thread_id,
        assistant_messages=_safe_assistant_messages(result),
        interrupt=_extract_interrupt_payload(result),
    )


@app.post("/api/resume", response_model=ChatResponse)
def resume(req: ResumeRequest) -> ChatResponse:
    invoke_config = {"configurable": {"thread_id": req.thread_id}}
    try:
        result = GRAPH.invoke(Command(resume=req.resume), invoke_config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Graph error: {e}")

    return ChatResponse(
        thread_id=req.thread_id,
        assistant_messages=_safe_assistant_messages(result),
        interrupt=_extract_interrupt_payload(result),
    )


# -----------------------------
# Static UI serving (SPA)
# -----------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UI_BUILD_DIR = PROJECT_ROOT / "Minimal Chatbot Interface Design" / "build"

@app.get("/")
def spa_root():
    """Serve the UI entrypoint."""
    if not UI_BUILD_DIR.exists():
        raise HTTPException(
            status_code=404,
            detail="UI build not found. Run `npm run build` in the UI folder.",
        )
    return FileResponse(str(UI_BUILD_DIR / "index.html"))


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    """Serve index.html for client-side routes (but only if UI build exists)."""
    # Never let the SPA fallback swallow API routes.
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")

    if not UI_BUILD_DIR.exists():
        raise HTTPException(
            status_code=404,
            detail="UI build not found. Run `npm run build` in the UI folder.",
        )

    # If the path corresponds to an actual file in the build directory, serve it.
    candidate = (UI_BUILD_DIR / full_path).resolve()
    try:
        candidate.relative_to(UI_BUILD_DIR.resolve())
    except Exception:
        candidate = UI_BUILD_DIR / "index.html"

    if candidate.exists() and candidate.is_file():
        return FileResponse(str(candidate))

    # Default SPA fallback
    return FileResponse(str(UI_BUILD_DIR / "index.html"))


