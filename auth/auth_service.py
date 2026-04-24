"""
AuthService — user management and token issuance for the Decision System.

Uses only Python built-ins for cryptography:
- ``hashlib.pbkdf2_hmac`` for password hashing (PBKDF2-HMAC-SHA256).
- ``hmac`` + ``hashlib`` + ``base64`` + ``json`` for JWT-style signed tokens.

Token format::

    base64url(payload_json).hex(hmac_sha256(base64url(payload_json), SECRET_KEY))

The SQLite database is created automatically at first use.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

from auth.user_context import UserContext

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent
_DEFAULT_DB_PATH = _HERE / "users.db"
_DEV_SECRET_KEY = "dev-secret-change-in-production-please"  # nosec

_DEMO_USERS: list[tuple[str, str, str]] = [
    ("admin", "admin123", "admin"),
    ("alice", "alice123", "analyst"),
    ("bob", "bob123", "manager"),
    ("carol", "carol123", "viewer"),
]

_PBKDF2_ITERATIONS = 260_000
_PBKDF2_HASH = "sha256"
_SALT_BYTES = 32


# ---------------------------------------------------------------------------
# AuthService
# ---------------------------------------------------------------------------


class AuthService:
    """Manages user accounts and signed authentication tokens.

    Args:
        db_path:    Path to the SQLite database file.  Defaults to
                    ``auth/users.db`` relative to this module.
        secret_key: HMAC signing key for tokens.  Defaults to the value of
                    the ``AUTH_SECRET_KEY`` environment variable, falling back
                    to a hard-coded development default.
    """

    def __init__(
        self,
        db_path: Optional[str | Path] = None,
        secret_key: Optional[str] = None,
    ) -> None:
        self._db_path = Path(db_path) if db_path is not None else _DEFAULT_DB_PATH
        self._secret_key: str = (
            secret_key
            or os.environ.get("AUTH_SECRET_KEY", _DEV_SECRET_KEY)
        )

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Return a new SQLite connection with row_factory set."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        """Create the users table if it does not exist, then seed demo users."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT    NOT NULL UNIQUE,
                    pw_hash  TEXT    NOT NULL,
                    salt     TEXT    NOT NULL,
                    role     TEXT    NOT NULL DEFAULT 'viewer'
                )
                """
            )
            conn.commit()

            # Seed only when the table is empty
            row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
            if row["n"] == 0:
                for username, password, role in _DEMO_USERS:
                    self._insert_user(conn, username, password, role)
                conn.commit()

    def _insert_user(
        self,
        conn: sqlite3.Connection,
        username: str,
        password: str,
        role: str,
    ) -> sqlite3.Row:
        salt_bytes = os.urandom(_SALT_BYTES)
        pw_hash = self._hash_password(password, salt_bytes)
        salt_hex = salt_bytes.hex()
        conn.execute(
            "INSERT INTO users (username, pw_hash, salt, role) VALUES (?, ?, ?, ?)",
            (username, pw_hash, salt_hex, role),
        )
        return conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

    # ------------------------------------------------------------------
    # Password hashing
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_password(password: str, salt: bytes) -> str:
        """Return a hex-encoded PBKDF2-HMAC-SHA256 digest."""
        dk = hashlib.pbkdf2_hmac(
            _PBKDF2_HASH,
            password.encode("utf-8"),
            salt,
            _PBKDF2_ITERATIONS,
        )
        return dk.hex()

    def _verify_password_hash(self, password: str, salt_hex: str, stored_hash: str) -> bool:
        salt = bytes.fromhex(salt_hex)
        candidate = self._hash_password(password, salt)
        return hmac.compare_digest(candidate, stored_hash)

    # ------------------------------------------------------------------
    # Token helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _b64url_encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    @staticmethod
    def _b64url_decode(s: str) -> bytes:
        # Restore padding
        padding = 4 - len(s) % 4
        if padding != 4:
            s += "=" * padding
        return base64.urlsafe_b64decode(s)

    def _sign(self, payload_b64: str) -> str:
        """Return a hex HMAC-SHA256 signature over *payload_b64*."""
        sig = hmac.new(
            self._secret_key.encode("utf-8"),
            payload_b64.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return sig.hex()

    def create_token(self, user_context: UserContext, expires_hours: float = 8) -> str:
        """Issue a signed token for *user_context*.

        Args:
            user_context:  The authenticated user.
            expires_hours: Token lifetime in hours (default 8).

        Returns:
            An opaque token string of the form ``<payload_b64>.<hex_sig>``.
        """
        exp = int(time.time()) + int(expires_hours * 3600)
        payload = {
            "sub": user_context.user_id,
            "username": user_context.username,
            "role": user_context.role,
            "exp": exp,
        }
        payload_b64 = self._b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        sig = self._sign(payload_b64)
        return f"{payload_b64}.{sig}"

    def verify_token(self, token: str) -> Optional[UserContext]:
        """Validate *token* and return the corresponding :class:`UserContext`.

        Returns ``None`` if the token is malformed, the signature is invalid,
        or the token has expired.
        """
        try:
            payload_b64, sig = token.rsplit(".", 1)
        except ValueError:
            return None

        # Constant-time signature check
        expected_sig = self._sign(payload_b64)
        if not hmac.compare_digest(expected_sig, sig):
            return None

        try:
            payload_bytes = self._b64url_decode(payload_b64)
            payload: dict = json.loads(payload_bytes)
        except Exception:
            return None

        if time.time() > payload.get("exp", 0):
            return None

        try:
            return UserContext(
                user_id=str(payload["sub"]),
                username=payload["username"],
                role=payload["role"],
            )
        except (KeyError, TypeError):
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_user(self, username: str, password: str, role: str) -> dict:
        """Create a new user and return a dict with ``id``, ``username``, ``role``.

        Raises:
            sqlite3.IntegrityError: If *username* already exists.
        """
        with self._connect() as conn:
            self._insert_user(conn, username, password, role)
            conn.commit()
            row = conn.execute(
                "SELECT id, username, role FROM users WHERE username = ?", (username,)
            ).fetchone()
            return {"id": row["id"], "username": row["username"], "role": row["role"]}

    def verify_password(self, username: str, password: str) -> Optional[UserContext]:
        """Return a :class:`UserContext` if credentials are valid, else ``None``."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, username, pw_hash, salt, role FROM users WHERE username = ?",
                (username,),
            ).fetchone()

        if row is None:
            return None
        if not self._verify_password_hash(password, row["salt"], row["pw_hash"]):
            return None

        return UserContext(
            user_id=str(row["id"]),
            username=row["username"],
            role=row["role"],
        )
