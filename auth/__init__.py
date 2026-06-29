"""Auth Manager — 统一认证入口

对接路径:
  前端 (Firebase) → FirebaseProvider.verify_token(id_token) → 后端
  CLI  (Local)     → LocalProvider.verify_token(email:password) → 后端
  MCP  (JWT)       → JWTService.verify(token) → 后端

所有路径最终返回 User 对象 + JWT session token。
"""

import os
from typing import Optional
from .models import User, UserStore
from .jwt_service import JWTService
from .providers import AuthProvider, FirebaseProvider, LocalProvider


class AuthManager:
    """统一认证管理器

    用法:
        auth = AuthManager()
        user, jwt = auth.login("firebase", id_token)
        user, jwt = auth.login("local", "email:password")
        claims = auth.verify_jwt(jwt_token)
    """

    def __init__(
        self,
        db_path: str = "./data/edis.db",
        jwt_secret: str = None,
    ):
        self.db_path = db_path
        self.user_store = UserStore(db_path)
        self.jwt = JWTService(jwt_secret)

        # 延迟初始化 provider — 按需加载
        self._providers: dict[str, AuthProvider] = {}

    def _get_provider(self, provider_name: str) -> AuthProvider:
        if provider_name not in self._providers:
            if provider_name == "firebase":
                self._providers["firebase"] = FirebaseProvider()
            elif provider_name == "local":
                self._providers["local"] = LocalProvider(self.db_path)
            else:
                raise ValueError(f"Unknown provider: {provider_name}")
        return self._providers[provider_name]

    def login(self, provider: str, credential: str) -> tuple[Optional[User], Optional[str]]:
        """认证用户，返回 (User, JWT token)

        provider: "firebase" | "local"
        credential:
          - firebase: Firebase ID Token (string)
          - local:    "email:password"

        Returns: (User, jwt_token) 或 (None, None)
        """
        auth_provider = self._get_provider(provider)

        # 1. Provider 验证凭证
        user_info = auth_provider.verify_token(credential)
        if not user_info:
            return None, None

        # 2. 创建/更新本地用户记录
        user = User(
            firebase_uid=user_info["uid"],
            email=user_info.get("email", ""),
            display_name=user_info.get("name", ""),
            avatar=user_info.get("picture", ""),
            security_clearance=1,
        )
        user = self.user_store.upsert(user)

        # 3. 签发 JWT
        jwt_token = self.jwt.generate({
            "sub": user.firebase_uid,
            "email": user.email,
            "provider": provider,
            "tenant_id": user.tenant_id,
        })

        return user, jwt_token

    def register(self, provider: str, email: str, password: str,
                 name: str = "") -> tuple[Optional[User], Optional[str]]:
        """注册新用户"""
        auth_provider = self._get_provider(provider)

        # 1. Provider 端创建用户
        user_info = auth_provider.create_user(email, password, name)
        if not user_info:
            return None, None

        # 2. 本地创建记录
        user = User(
            firebase_uid=user_info["uid"],
            email=user_info.get("email", email),
            display_name=user_info.get("name", name),
            security_clearance=1,
        )
        user = self.user_store.upsert(user)

        # 3. 签发 JWT
        jwt_token = self.jwt.generate({
            "sub": user.firebase_uid,
            "email": user.email,
            "provider": provider,
            "tenant_id": user.tenant_id,
        })

        return user, jwt_token

    def verify_jwt(self, token: str) -> Optional[dict]:
        """验证 JWT，返回 claims (含 sub, email, provider, tenant_id)"""
        return self.jwt.verify(token)

    def refresh_jwt(self, token: str) -> Optional[str]:
        """刷新 JWT"""
        return self.jwt.refresh(token)

    def get_user(self, firebase_uid: str) -> Optional[User]:
        """按 UID 获取用户"""
        return self.user_store.get(firebase_uid)

    def logout(self, token: str) -> bool:
        """登出 — 使 JWT 失效（生产环境应加入黑名单/Redis）

        当前实现：返回 True（token 到期后自然失效）。
        """
        return self.verify_jwt(token) is not None

    def close(self):
        self.user_store.close()
