"""A local, encrypted secret store standing in for a real vault (TDD s6, product rule 9).

`POST /connectors/{key}/secrets` mints a reference like "vault://shiftleft/jira/api_token" and,
until this module existed, threw the value away right after - nothing anywhere resolved that
reference back to anything, so a "Test connection" button could never make a real call with a
credential someone actually typed in. This is the first thing that does: `write` encrypts the
value under its reference, and `read` decrypts it back, at the moment a connector calls out.

There is still no HTTP endpoint that returns a secret value - this only lets server-side code
that already holds a valid ref use the value it names. Swapping this for a real vault later is a
matter of giving `write`/`read` a different backend; nothing that calls them needs to change.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.secret import VaultSecret

# Local-dev convenience only: a key generated once and persisted here so restarting the server
# doesn't lock out every credential already rotated in. Never read outside `_local_dev_key`, and
# `_production_guards` (app/core/config.py) refuses to boot production without an explicit key.
_DEV_KEY_FILE = Path(__file__).resolve().parents[2] / ".vault_key"


def _local_dev_key() -> bytes:
    if _DEV_KEY_FILE.exists():
        return _DEV_KEY_FILE.read_bytes().strip()
    key = Fernet.generate_key()
    _DEV_KEY_FILE.write_bytes(key)
    return key


@lru_cache
def _fernet() -> Fernet:
    settings = get_settings()
    key = settings.vault_encryption_key.get_secret_value() if settings.vault_encryption_key else None
    return Fernet(key.encode() if key else _local_dev_key())


async def write(ref: str, value: str) -> None:
    """Encrypts `value` under `ref`, replacing whatever was stored there before."""
    ciphertext = _fernet().encrypt(value.encode()).decode()
    async with SessionLocal() as session:
        existing = await session.get(VaultSecret, ref)
        if existing is None:
            session.add(VaultSecret(ref=ref, ciphertext=ciphertext))
        else:
            existing.ciphertext = ciphertext
        await session.commit()


async def read(ref: str) -> str | None:
    """None if nothing was ever written for `ref`, or if it can't be decrypted with the key
    this process holds now (e.g. the encryption key rotated) - never a stale or partial value.
    """
    async with SessionLocal() as session:
        row = await session.get(VaultSecret, ref)
    if row is None:
        return None
    try:
        return _fernet().decrypt(row.ciphertext.encode()).decode()
    except InvalidToken:
        return None


async def stored(ref: str) -> bool:
    """Whether anything is stored for `ref`, without decrypting it.

    `read` returning None cannot tell "nobody ever set this" from "set on a machine whose key
    this one doesn't have" - and those call for different words in front of a person.
    """
    async with SessionLocal() as session:
        return await session.get(VaultSecret, ref) is not None


async def delete(ref: str) -> None:
    async with SessionLocal() as session:
        row = await session.get(VaultSecret, ref)
        if row is not None:
            await session.delete(row)
            await session.commit()
