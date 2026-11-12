from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

# Force mock inference for CI / no-GPU smoke
os.environ["MOCK_INFERENCE"] = "1"
os.environ["EIGENEAI_ADMIN_SECRET"] = "test-admin-secret"
os.environ["EIGENEAI_DATA_DIR"] = str(Path(__file__).parent / "_tmp_data")
os.environ["LLAMA_CPP_URL"] = ""

from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_data(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("EIGENEAI_DATA_DIR", str(data))
    monkeypatch.setenv("MOCK_INFERENCE", "1")
    monkeypatch.setenv("EIGENEAI_ADMIN_SECRET", "test-admin-secret")
    monkeypatch.setenv("LLAMA_CPP_URL", "")
    # Reload settings into running app state happens in lifespan
    yield


@pytest.mark.asyncio
async def test_health_invite_chat_revoke(tmp_path, monkeypatch):
    monkeypatch.setenv("EIGENEAI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MOCK_INFERENCE", "1")
    monkeypatch.setenv("EIGENEAI_ADMIN_SECRET", "test-admin-secret")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # lifespan
        async with app.router.lifespan_context(app):
            h = await client.get("/health")
            assert h.status_code == 200
            body = h.json()
            assert body["status"] == "ok"
            assert body["mock_inference"] is True
            assert body["default_model"].startswith("Qwen2.5-14B")

            inv = await client.post(
                "/admin/invites",
                headers={"X-Admin-Secret": "test-admin-secret"},
                json={"label": "Anna"},
            )
            assert inv.status_code == 200
            code = inv.json()["code"]

            redeemed = await client.post(
                "/api/auth/redeem",
                json={"code": code, "name": "Anna"},
            )
            assert redeemed.status_code == 200
            token = redeemed.json()["token"]
            account_id = redeemed.json()["account_id"]
            assert token.startswith("eai_")

            me = await client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
            assert me.status_code == 200
            assert me.json()["name"] == "Anna"

            chat = await client.post(
                "/api/chats",
                headers={"Authorization": f"Bearer {token}"},
                json={"title": "Test"},
            )
            assert chat.status_code == 200
            chat_id = chat.json()["id"]

            # Second account isolation
            inv2 = await client.post(
                "/admin/invites",
                headers={"X-Admin-Secret": "test-admin-secret"},
                json={"label": "Ben"},
            )
            tok2 = (
                await client.post(
                    "/api/auth/redeem",
                    json={"code": inv2.json()["code"], "name": "Ben"},
                )
            ).json()["token"]

            # Anna streams a completion
            async with client.stream(
                "POST",
                "/v1/chat/completions",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "messages": [{"role": "user", "content": "Hallo"}],
                    "stream": True,
                    "chat_id": chat_id,
                },
            ) as resp:
                assert resp.status_code == 200
                text = ""
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        obj = json.loads(data)
                        if "eigeneai" in obj:
                            continue
                        if "error" in obj:
                            pytest.fail(obj["error"]["message"])
                        delta = obj["choices"][0].get("delta") or {}
                        text += delta.get("content") or ""
                assert "Mock-Modus" in text or "EigeneAI" in text

            hist = await client.get(
                f"/api/chats/{chat_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert hist.status_code == 200
            msgs = hist.json()["messages"]
            assert any(m["role"] == "user" for m in msgs)
            assert any(m["role"] == "assistant" for m in msgs)

            # Ben cannot see Anna's chat
            forbidden = await client.get(
                f"/api/chats/{chat_id}",
                headers={"Authorization": f"Bearer {tok2}"},
            )
            assert forbidden.status_code == 404

            ben_chats = await client.get(
                "/api/chats",
                headers={"Authorization": f"Bearer {tok2}"},
            )
            assert ben_chats.json()["chats"] == []

            # Revoke Anna
            rev = await client.post(
                f"/admin/accounts/{account_id}/revoke",
                headers={"X-Admin-Secret": "test-admin-secret"},
            )
            assert rev.status_code == 200
            denied = await client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
            assert denied.status_code == 401
