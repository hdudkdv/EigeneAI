from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .config import Settings, get_settings
from .db import Store
from .inference import health_backend, list_models, stream_chat_completion
from .queue import InferenceQueue


class AppState:
    settings: Settings
    store: Store
    queue: InferenceQueue
    web_mounted: bool = False


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .config import refresh_settings

    settings = refresh_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    store = Store(settings.db_path, settings.accounts_dir)
    await store.connect()
    state.settings = settings
    state.store = store
    state.web_mounted = False
    # MVP: 1 GPU worker; GPU_COUNT soft-reserve for Phase 2
    workers = 1 if settings.gpu_count <= 1 else min(settings.gpu_count, 4)
    state.queue = InferenceQueue(maxsize=settings.gpu_queue_size, workers=workers)
    mount_web(app, settings)
    yield
    await store.close()


app = FastAPI(
    title="EigeneAI Gateway",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def require_account(
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Bearer-Token erforderlich")
    token = authorization.split(" ", 1)[1].strip()
    account = await state.store.get_account_by_token(token)
    if not account:
        raise HTTPException(status_code=401, detail="Ungültiges oder widerrufenes Token")
    return account


async def require_admin(
    authorization: Annotated[str | None, Header()] = None,
    x_admin_secret: Annotated[str | None, Header()] = None,
) -> None:
    secret = state.settings.admin_secret
    provided = None
    if x_admin_secret:
        provided = x_admin_secret
    elif authorization and authorization.lower().startswith("bearer "):
        provided = authorization.split(" ", 1)[1].strip()
    if not provided or provided != secret:
        raise HTTPException(status_code=403, detail="Admin-Secret ungültig")


@app.get("/health")
async def health():
    backend = await health_backend(state.settings)
    q = await state.queue.status()
    ok = bool(backend.get("ok")) or state.settings.use_mock
    return {
        "status": "ok" if ok else "degraded",
        "version": __version__,
        "default_model": state.settings.default_model,
        "gpu_count": state.settings.gpu_count,
        "queue": q,
        "backend": backend,
        "mock_inference": state.settings.use_mock,
    }


@app.get("/v1/models")
async def models(_: dict = Depends(require_account)):
    data = await list_models(state.settings)
    return {"object": "list", "data": data}


class RedeemBody(BaseModel):
    code: str
    name: str = Field(min_length=1, max_length=64)


class InviteBody(BaseModel):
    label: str = Field(min_length=1, max_length=64)
    expires_in_hours: float | None = 168.0


@app.post("/api/auth/redeem")
async def redeem_invite(body: RedeemBody):
    try:
        result = await state.store.redeem_invite(body.code, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@app.get("/api/me")
async def me(account: dict = Depends(require_account)):
    return {
        "id": account["id"],
        "name": account["name"],
        "created_at": account["created_at"],
        "token_prefix": account["token_prefix"],
    }


@app.post("/admin/invites", dependencies=[Depends(require_admin)])
async def create_invite(body: InviteBody):
    return await state.store.create_invite(body.label, body.expires_in_hours)


@app.get("/admin/accounts", dependencies=[Depends(require_admin)])
async def admin_list_accounts():
    return {"accounts": await state.store.list_accounts()}


@app.post("/admin/accounts/{account_id}/revoke", dependencies=[Depends(require_admin)])
async def admin_revoke(account_id: str):
    ok = await state.store.revoke_account(account_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Account nicht gefunden oder bereits widerrufen")
    return {"revoked": True, "account_id": account_id}


class CreateChatBody(BaseModel):
    title: str = "Neuer Chat"


@app.get("/api/chats")
async def api_list_chats(account: dict = Depends(require_account)):
    return {"chats": await state.store.list_chats(account["id"])}


@app.post("/api/chats")
async def api_create_chat(body: CreateChatBody, account: dict = Depends(require_account)):
    return await state.store.create_chat(account["id"], body.title)


@app.get("/api/chats/{chat_id}")
async def api_get_chat(chat_id: str, account: dict = Depends(require_account)):
    chat = await state.store.get_chat(account["id"], chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat nicht gefunden")
    messages = await state.store.list_messages(account["id"], chat_id)
    return {**chat, "messages": messages}


@app.delete("/api/chats/{chat_id}")
async def api_delete_chat(chat_id: str, account: dict = Depends(require_account)):
    ok = await state.store.delete_chat(account["id"], chat_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Chat nicht gefunden")
    return {"deleted": True}


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionBody(BaseModel):
    model: str | None = None
    messages: list[ChatMessage]
    stream: bool = True
    temperature: float = 0.7
    max_tokens: int | None = None
    chat_id: str | None = None


@app.post("/v1/chat/completions")
async def chat_completions(body: ChatCompletionBody, account: dict = Depends(require_account)):
    settings = state.settings
    model = body.model or settings.default_model
    messages = [m.model_dump() for m in body.messages]

    chat_id = body.chat_id
    if chat_id:
        chat = await state.store.get_chat(account["id"], chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat nicht gefunden")
        last_user = next((m for m in reversed(messages) if m["role"] == "user"), None)
        if last_user:
            existing = await state.store.list_messages(account["id"], chat_id)
            if (
                not existing
                or existing[-1]["content"] != last_user["content"]
                or existing[-1]["role"] != "user"
            ):
                await state.store.add_message(account["id"], chat_id, "user", last_user["content"])

    qstatus = await state.queue.status()
    queue_hint = qstatus["queue_depth"]

    if not body.stream:

        async def collect() -> str:
            parts: list[str] = []
            async for data in stream_chat_completion(
                settings,
                model=model,
                messages=messages,
                temperature=body.temperature,
                max_tokens=body.max_tokens,
            ):
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                    delta = obj["choices"][0].get("delta") or {}
                    if "content" in delta:
                        parts.append(delta["content"])
                except Exception:
                    continue
            return "".join(parts)

        try:
            content = await state.queue.run(account["id"], collect)
        except RuntimeError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc

        if chat_id:
            await state.store.add_message(account["id"], chat_id, "assistant", content)

        return {
            "id": "chatcmpl-eigeneai",
            "object": "chat.completion",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
        }

    async def event_gen():
        if queue_hint > 0:
            payload = {
                "eigeneai": {
                    "queue_position": queue_hint + 1,
                    "hint": "Anfrage in Warteschlange (1× GPU)",
                }
            }
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        collected: list[str] = []
        # Hold the GPU slot for the whole stream via a bridge queue
        import asyncio

        out: asyncio.Queue[str | None] = asyncio.Queue()
        error_box: list[BaseException] = []

        async def producer():
            async def work():
                async for data in stream_chat_completion(
                    settings,
                    model=model,
                    messages=messages,
                    temperature=body.temperature,
                    max_tokens=body.max_tokens,
                ):
                    await out.put(data)
                await out.put(None)

            try:
                await state.queue.run(account["id"], work)
            except BaseException as exc:  # noqa: BLE001
                error_box.append(exc)
                await out.put(None)

        task = asyncio.create_task(producer())
        try:
            while True:
                item = await out.get()
                if item is None:
                    break
                if item == "[DONE]":
                    yield "data: [DONE]\n\n"
                    continue
                try:
                    obj = json.loads(item)
                    delta = obj["choices"][0].get("delta") or {}
                    if "content" in delta:
                        collected.append(delta["content"])
                except Exception:
                    pass
                yield f"data: {item}\n\n"
            if error_box:
                err = error_box[0]
                yield f"data: {json.dumps({'error': {'message': str(err)}}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            await task
            if chat_id and collected:
                await state.store.add_message(
                    account["id"], chat_id, "assistant", "".join(collected)
                )

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.get("/api/queue")
async def api_queue(account: dict = Depends(require_account)):
    _ = account
    return await state.queue.status()


def mount_web(application: FastAPI, settings: Settings) -> None:
    if state.web_mounted:
        return
    candidates: list[Path] = []
    if settings.web_dist:
        candidates.append(settings.web_dist)
    here = Path(__file__).resolve()
    candidates.extend(
        [
            here.parents[2] / "web" / "dist",
            Path("/var/lib/ai/web"),
            Path("./web/dist"),
        ]
    )
    dist = next((d for d in candidates if d.is_dir() and (d / "index.html").exists()), None)
    if not dist:
        return

    assets = dist / "assets"
    if assets.is_dir():
        application.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @application.get("/")
    async def index():
        return FileResponse(dist / "index.html")

    @application.get("/manifest.webmanifest")
    async def manifest():
        return FileResponse(dist / "manifest.webmanifest")

    @application.get("/sw.js")
    async def sw():
        path = dist / "sw.js"
        if path.is_file():
            return FileResponse(path)
        raise HTTPException(status_code=404)

    @application.get("/favicon.svg")
    async def favicon():
        return FileResponse(dist / "favicon.svg")

    icons = dist / "icons"
    if icons.is_dir():
        application.mount("/icons", StaticFiles(directory=str(icons)), name="icons")

    state.web_mounted = True


def create_app() -> FastAPI:
    return app
