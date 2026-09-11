from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class VaultSecret(Base, TimestampMixin):
    """A local, encrypted stand-in for a real secret vault (TDD s6, product rule 9).

    Keyed by the same "vault://..." reference a ConnectorInstance already stores in its
    secret_refs - see app/services/vault.py, which is the only code that reads or writes this
    table. There is still no API endpoint anywhere that returns a value from it.
    """

    __tablename__ = "vault_secrets"

    ref: Mapped[str] = mapped_column(String(255), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)
