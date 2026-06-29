"""JWT Service — token 生成、验证、刷新

内部认证令牌。与 Firebase ID Token 互补：
  - Firebase: 前端 → 后端身份证明
  - JWT:      后端内部会话令牌（给 CLI/MCP 使用）
"""

import os
import time
import json
import hashlib
import hmac
import base64
from typing import Optional


class JWTService:
    """轻量 JWT 实现 — 无外部依赖

    生产环境可替换为 PyJWT / python-jose。
    """

    def __init__(self, secret: str = None):
        self.secret = secret or os.environ.get(
            "EDIS_JWT_SECRET",
            hashlib.sha256(os.urandom(32)).hexdigest(),
        )
        self._token_ttl = int(os.environ.get("EDIS_JWT_TTL", "86400"))  # 24h

    def generate(self, payload: dict, ttl: int = None) -> str:
        """生成 JWT token

        payload 必须包含 'sub' (firebase_uid)
        """
        ttl = ttl or self._token_ttl
        now = int(time.time())

        header = {"alg": "HS256", "typ": "JWT"}
        claims = {
            **payload,
            "iat": now,
            "exp": now + ttl,
            "jti": hashlib.sha256(os.urandom(16)).hexdigest()[:12],
        }

        header_b64 = self._b64url(json.dumps(header, separators=(",", ":")).encode())
        claims_b64 = self._b64url(json.dumps(claims, separators=(",", ":")).encode())
        signing_input = f"{header_b64}.{claims_b64}"

        sig = hmac.new(
            self.secret.encode(), signing_input.encode(), hashlib.sha256
        ).digest()
        sig_b64 = self._b64url(sig)

        return f"{signing_input}.{sig_b64}"

    def verify(self, token: str) -> Optional[dict]:
        """验证 token，返回 claims 或 None"""
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None

            header_b64, claims_b64, sig_b64 = parts
            signing_input = f"{header_b64}.{claims_b64}"

            expected_sig = hmac.new(
                self.secret.encode(), signing_input.encode(), hashlib.sha256
            ).digest()

            actual_sig = self._b64url_decode(sig_b64)
            if not hmac.compare_digest(expected_sig, actual_sig):
                return None

            claims = json.loads(self._b64url_decode(claims_b64).decode())

            # 检查过期
            if claims.get("exp", 0) < time.time():
                return None

            return claims
        except Exception:
            return None

    def refresh(self, token: str, ttl: int = None) -> Optional[str]:
        """刷新 token（生成新 token，保留原 claims）"""
        claims = self.verify(token)
        if not claims:
            return None

        # 去掉内部字段后重新签发
        new_payload = {
            k: v for k, v in claims.items()
            if k not in ("iat", "exp", "jti")
        }
        return self.generate(new_payload, ttl)

    @staticmethod
    def _b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    @staticmethod
    def _b64url_decode(data: str) -> bytes:
        padding = 4 - len(data) % 4
        if padding != 4:
            data += "=" * padding
        return base64.urlsafe_b64decode(data)
