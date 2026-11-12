from __future__ import annotations

import json
import secrets
import time
import uuid
from pathlib import Path
from typing import Any

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,
  token_prefix TEXT NOT NULL,
  created_at REAL NOT NULL,
  revoked_at REAL,
  invite_id TEXT
);

CREATE TABLE IF NOT EXISTS invites (
  id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  code TEXT NOT NULL UNIQUE,
  created_at REAL NOT NULL,
  expires_at REAL,
  used_at REAL,
  used_by_account_id TEXT
);

CREATE TABLE IF NOT EXISTS chats (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  title TEXT NOT NULL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  FOREIGN KEY(account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  chat_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at REAL NOT NULL,
  FOREIGN KEY(chat_id) REFERENCES chats(id)
);

CREATE INDEX IF NOT EXISTS idx_chats_account ON chats(account_id);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id);
CREATE INDEX IF NOT EXISTS idx_accounts_token ON accounts(token_hash);
"""


def hash_token(token: str) -> str:
    import hashlib

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return f"eai_{secrets.token_urlsafe(32)}"


def new_invite_code() -> str:
    return secrets.token_urlsafe(16)


class Store:
    def __init__(self, db_path: Path, accounts_dir: Path) -> None:
        self.db_path = db_path
        self.accounts_dir = accounts_dir
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.accounts_dir.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def db(self) -> aiosqlite.Connection:
        if not self._conn:
            raise RuntimeError("Store not connected")
        return self._conn

    async def create_invite(
        self, label: str, expires_in_hours: float | None = 168.0
    ) -> dict[str, Any]:
        invite_id = str(uuid.uuid4())
        code = new_invite_code()
        now = time.time()
        expires_at = now + expires_in_hours * 3600 if expires_in_hours else None
        await self.db.execute(
            "INSERT INTO invites (id, label, code, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (invite_id, label, code, now, expires_at),
        )
        await self.db.commit()
        return {
            "id": invite_id,
            "label": label,
            "code": code,
            "created_at": now,
            "expires_at": expires_at,
        }

    async def redeem_invite(self, code: str, name: str) -> dict[str, Any]:
        cur = await self.db.execute(
            "SELECT * FROM invites WHERE code = ?", (code.strip(),)
        )
        row = await cur.fetchone()
        if not row:
            raise ValueError("Einladung ungültig")
        if row["used_at"] is not None:
            raise ValueError("Einladung bereits verwendet")
        if row["expires_at"] is not None and row["expires_at"] < time.time():
            raise ValueError("Einladung abgelaufen")

        account_id = str(uuid.uuid4())
        token = new_token()
        token_hash = hash_token(token)
        now = time.time()
        await self.db.execute(
            """INSERT INTO accounts (id, name, token_hash, token_prefix, created_at, invite_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (account_id, name.strip() or row["label"], token_hash, token[:12], now, row["id"]),
        )
        await self.db.execute(
            "UPDATE invites SET used_at = ?, used_by_account_id = ? WHERE id = ?",
            (now, account_id, row["id"]),
        )
        await self.db.commit()
        (self.accounts_dir / account_id / "chats").mkdir(parents=True, exist_ok=True)
        return {
            "account_id": account_id,
            "name": name.strip() or row["label"],
            "token": token,
            "created_at": now,
        }

    async def get_account_by_token(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        cur = await self.db.execute(
            "SELECT * FROM accounts WHERE token_hash = ?",
            (hash_token(token),),
        )
        row = await cur.fetchone()
        if not row:
            return None
        if row["revoked_at"] is not None:
            return None
        return dict(row)

    async def list_accounts(self) -> list[dict[str, Any]]:
        cur = await self.db.execute(
            "SELECT id, name, token_prefix, created_at, revoked_at FROM accounts ORDER BY created_at"
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def revoke_account(self, account_id: str) -> bool:
        cur = await self.db.execute(
            "UPDATE accounts SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
            (time.time(), account_id),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def list_chats(self, account_id: str) -> list[dict[str, Any]]:
        cur = await self.db.execute(
            "SELECT id, title, created_at, updated_at FROM chats WHERE account_id = ? ORDER BY updated_at DESC",
            (account_id,),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def create_chat(self, account_id: str, title: str = "Neuer Chat") -> dict[str, Any]:
        chat_id = str(uuid.uuid4())
        now = time.time()
        await self.db.execute(
            "INSERT INTO chats (id, account_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (chat_id, account_id, title, now, now),
        )
        await self.db.commit()
        return {"id": chat_id, "title": title, "created_at": now, "updated_at": now}

    async def get_chat(self, account_id: str, chat_id: str) -> dict[str, Any] | None:
        cur = await self.db.execute(
            "SELECT * FROM chats WHERE id = ? AND account_id = ?",
            (chat_id, account_id),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def delete_chat(self, account_id: str, chat_id: str) -> bool:
        chat = await self.get_chat(account_id, chat_id)
        if not chat:
            return False
        await self.db.execute(
            "DELETE FROM messages WHERE chat_id = ? AND account_id = ?",
            (chat_id, account_id),
        )
        await self.db.execute(
            "DELETE FROM chats WHERE id = ? AND account_id = ?",
            (chat_id, account_id),
        )
        await self.db.commit()
        return True

    async def list_messages(self, account_id: str, chat_id: str) -> list[dict[str, Any]]:
        chat = await self.get_chat(account_id, chat_id)
        if not chat:
            return []
        cur = await self.db.execute(
            """SELECT id, role, content, created_at FROM messages
               WHERE chat_id = ? AND account_id = ? ORDER BY created_at""",
            (chat_id, account_id),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def add_message(
        self, account_id: str, chat_id: str, role: str, content: str
    ) -> dict[str, Any]:
        msg_id = str(uuid.uuid4())
        now = time.time()
        await self.db.execute(
            """INSERT INTO messages (id, chat_id, account_id, role, content, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (msg_id, chat_id, account_id, role, content, now),
        )
        title_update = None
        if role == "user":
            cur = await self.db.execute(
                "SELECT COUNT(*) AS c FROM messages WHERE chat_id = ?", (chat_id,)
            )
            count_row = await cur.fetchone()
            if count_row and count_row["c"] == 1:
                title_update = (content.strip()[:48] or "Neuer Chat")
        if title_update:
            await self.db.execute(
                "UPDATE chats SET updated_at = ?, title = ? WHERE id = ? AND account_id = ?",
                (now, title_update, chat_id, account_id),
            )
        else:
            await self.db.execute(
                "UPDATE chats SET updated_at = ? WHERE id = ? AND account_id = ?",
                (now, chat_id, account_id),
            )
        await self.db.commit()
        # Mirror lightweight index under per-account dir (plan path shape)
        mirror = self.accounts_dir / account_id / "chats" / f"{chat_id}.jsonl"
        mirror.parent.mkdir(parents=True, exist_ok=True)
        with mirror.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"id": msg_id, "role": role, "content": content, "created_at": now}, ensure_ascii=False) + "\n")
        return {"id": msg_id, "role": role, "content": content, "created_at": now}
