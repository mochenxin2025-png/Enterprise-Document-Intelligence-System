"""Auth Providers — 可替换的身份认证后端

设计:
  - AuthProvider (ABC) → FirebaseProvider / LocalProvider
  - 前端用 Firebase，CLI 用 Local，统一接口
"""

import os
import json
import hashlib
from abc import ABC, abstractmethod
from typing import Optional


# ── Auth Provider Interface ─────────────────────

class AuthProvider(ABC):
    """身份认证抽象 — 所有 provider 实现此接口"""

    @abstractmethod
    def verify_token(self, token: str) -> Optional[dict]:
        """验证身份 token，返回用户信息 dict

        Returns: {"uid": str, "email": str, "name": str, "picture": str}
        验证失败返回 None
        """
        ...

    @abstractmethod
    def create_user(self, email: str, password: str, name: str = "") -> Optional[dict]:
        """创建新用户（provider 端）"""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        ...


# ── Firebase Provider ───────────────────────────

class FirebaseProvider(AuthProvider):
    """Firebase Admin SDK 集成 — 验证 Google-issued ID tokens

    要求环境变量 FIREBASE_SERVICE_ACCOUNT_JSON 或 FIREBASE_PROJECT_ID。

    使用 firebase-admin pip 包（可选依赖）。
    如果包未安装，verify_token 会明确报错而不是静默失败。
    """

    NAME = "firebase"

    def __init__(self):
        self._app = None
        self._initialized = False

    def _ensure_initialized(self):
        if self._initialized:
            return
        try:
            import firebase_admin
            from firebase_admin import credentials, auth as fb_auth

            cred_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "")
            project_id = os.environ.get("FIREBASE_PROJECT_ID", "")

            if cred_json:
                cred_dict = json.loads(cred_json)
                cred = credentials.Certificate(cred_dict)
            elif project_id:
                # Application Default Credentials
                cred = credentials.ApplicationDefault()
            else:
                raise RuntimeError(
                    "Firebase credentials not configured. "
                    "Set FIREBASE_SERVICE_ACCOUNT_JSON or FIREBASE_PROJECT_ID."
                )

            self._app = firebase_admin.initialize_app(cred, name="edis-auth")
            self._fb_auth = fb_auth
            self._initialized = True
        except ImportError:
            raise RuntimeError(
                "firebase-admin not installed. Run: uv pip install firebase-admin"
            )

    def verify_token(self, token: str) -> Optional[dict]:
        """验证 Firebase ID Token"""
        self._ensure_initialized()
        try:
            decoded = self._fb_auth.verify_id_token(token)
            return {
                "uid": decoded.get("uid", ""),
                "email": decoded.get("email", ""),
                "name": decoded.get("name", ""),
                "picture": decoded.get("picture", ""),
                "provider": "firebase",
            }
        except Exception:
            return None

    def create_user(self, email: str, password: str, name: str = "") -> Optional[dict]:
        """创建 Firebase 用户（Admin SDK）"""
        self._ensure_initialized()
        try:
            user = self._fb_auth.create_user(
                email=email,
                password=password,
                display_name=name,
            )
            return {
                "uid": user.uid,
                "email": user.email,
                "name": user.display_name or "",
                "picture": "",
                "provider": "firebase",
            }
        except Exception:
            return None

    @property
    def provider_name(self) -> str:
        return self.NAME


# ── Local Provider (CLI / 开发用) ────────────────

class LocalProvider(AuthProvider):
    """本地认证 — 用于 CLI 和开发环境，无需外部服务

    使用 email + password hash 本地存储。
    仅用于无前端场景（CLI / MCP）。
    """

    NAME = "local"

    def __init__(self, db_path: str = "./data/edis.db"):
        self._db_path = db_path
        import sqlite3
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS local_auth (
                email TEXT PRIMARY KEY,
                password_hash TEXT,
                display_name TEXT DEFAULT '',
                created_at REAL
            )
        """)
        self._conn.commit()

    def verify_token(self, token: str) -> Optional[dict]:
        """验证本地 token — 格式: email:password"""
        try:
            email, password = token.split(":", 1)
        except ValueError:
            return None

        row = self._conn.execute(
            "SELECT password_hash, display_name FROM local_auth WHERE email = ?",
            (email,),
        ).fetchone()
        if not row:
            return None

        if not self._verify_hash(password, row[0]):
            return None

        return {
            "uid": hashlib.sha256(email.encode()).hexdigest()[:16],
            "email": email,
            "name": row[1] or "",
            "picture": "",
            "provider": "local",
        }

    def create_user(self, email: str, password: str, name: str = "") -> Optional[dict]:
        """创建本地用户"""
        import time
        uid = hashlib.sha256(email.encode()).hexdigest()[:16]
        pwd_hash = self._hash(password)

        try:
            self._conn.execute(
                "INSERT INTO local_auth (email, password_hash, display_name, created_at) "
                "VALUES (?, ?, ?, ?)",
                (email, pwd_hash, name, time.time()),
            )
            self._conn.commit()
            return {
                "uid": uid, "email": email, "name": name,
                "picture": "", "provider": "local",
            }
        except Exception:
            return None

    @property
    def provider_name(self) -> str:
        return self.NAME

    @staticmethod
    def _hash(password: str) -> str:
        """Hash password with bcrypt (preferred) or pbkdf2_sha256 (fallback)."""
        try:
            import bcrypt
            return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        except ImportError:
            pass

        # Fallback: pbkdf2_hmac — salt embedded in output
        salt = os.urandom(16).hex()
        h = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), 100000
        ).hex()
        return f"pbkdf2:{salt}:{h}"

    @staticmethod
    def _verify_hash(password: str, stored_hash: str) -> bool:
        """Verify password against stored hash (bcrypt or pbkdf2)."""
        if stored_hash.startswith("pbkdf2:"):
            parts = stored_hash.split(":")
            if len(parts) != 3:
                return False
            _, salt, expected = parts
            actual = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), salt.encode(), 100000
            ).hex()
            return LocalProvider._timing_safe_compare(
                f"pbkdf2:{salt}:{actual}", stored_hash)

        try:
            import bcrypt
            return bcrypt.checkpw(password.encode(), stored_hash.encode())
        except ImportError:
            return False

    @staticmethod
    def _timing_safe_compare(a: str, b: str) -> bool:
        if len(a) != len(b):
            return False
        result = 0
        for x, y in zip(a, b):
            result |= ord(x) ^ ord(y)
        return result == 0

    def close(self):
        self._conn.close()
