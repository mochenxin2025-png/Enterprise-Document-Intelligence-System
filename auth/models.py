"""Auth models — User dataclass + SQLite schema

企业级 RAG 用户认证模型。与现有 L2 权限系统集成。
"""

import time
import sqlite3
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class User:
    """用户模型 — 最小字段集，后续可扩展"""
    firebase_uid: str                   # Firebase UID (provider-agnostic unique ID)
    email: str = ""
    display_name: str = ""
    avatar: str = ""
    role: str = ""                      # → 对接 L2 permissions.role
    department: str = ""                # → 对接 L2 permissions.department
    security_clearance: int = 1         # → 对接 L2 密级
    tenant_id: str = "default"
    created_at: float = 0.0
    updated_at: float = 0.0

    @property
    def user_id(self) -> str:
        return self.firebase_uid

    def to_permission_context(self) -> dict:
        """转换为 L2 PermissionManager user_context"""
        return {
            "user_id": self.firebase_uid,
            "role": self.role,
            "department": self.department,
            "security_clearance": self.security_clearance,
        }

    def to_dict(self) -> dict:
        return {
            "firebase_uid": self.firebase_uid,
            "email": self.email,
            "display_name": self.display_name,
            "avatar": self.avatar,
            "role": self.role,
            "department": self.department,
            "security_clearance": self.security_clearance,
            "tenant_id": self.tenant_id,
        }


class UserStore:
    """SQLite 用户存储 — first-login 自动创建"""

    def __init__(self, db_path: str = "./data/edis.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_table()

    def _init_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                firebase_uid TEXT PRIMARY KEY,
                email TEXT DEFAULT '',
                display_name TEXT DEFAULT '',
                avatar TEXT DEFAULT '',
                role TEXT DEFAULT '',
                department TEXT DEFAULT '',
                security_clearance INTEGER DEFAULT 1,
                tenant_id TEXT DEFAULT 'default',
                created_at REAL,
                updated_at REAL
            )
        """)
        self.conn.commit()

    def upsert(self, user: User) -> User:
        """创建或更新用户记录（first-login 自动创建）"""
        now = time.time()
        existing = self.conn.execute(
            "SELECT created_at FROM users WHERE firebase_uid = ?",
            (user.firebase_uid,),
        ).fetchone()

        if existing:
            user.created_at = existing[0]
            user.updated_at = now
            self.conn.execute(
                "UPDATE users SET email=?, display_name=?, avatar=?, role=?, "
                "department=?, security_clearance=?, tenant_id=?, updated_at=? "
                "WHERE firebase_uid=?",
                (user.email, user.display_name, user.avatar, user.role,
                 user.department, user.security_clearance, user.tenant_id,
                 now, user.firebase_uid),
            )
        else:
            user.created_at = now
            user.updated_at = now
            self.conn.execute(
                "INSERT INTO users (firebase_uid, email, display_name, avatar, "
                "role, department, security_clearance, tenant_id, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (user.firebase_uid, user.email, user.display_name, user.avatar,
                 user.role, user.department, user.security_clearance, user.tenant_id,
                 now, now),
            )
        self.conn.commit()
        return user

    def get(self, firebase_uid: str) -> Optional[User]:
        """按 UID 查找用户"""
        row = self.conn.execute(
            "SELECT firebase_uid, email, display_name, avatar, role, department, "
            "security_clearance, tenant_id, created_at, updated_at "
            "FROM users WHERE firebase_uid = ?",
            (firebase_uid,),
        ).fetchone()

        if not row:
            return None

        return User(
            firebase_uid=row[0], email=row[1], display_name=row[2],
            avatar=row[3], role=row[4], department=row[5],
            security_clearance=row[6], tenant_id=row[7],
            created_at=row[8], updated_at=row[9],
        )

    def get_by_email(self, email: str) -> Optional[User]:
        """按 email 查找用户"""
        row = self.conn.execute(
            "SELECT firebase_uid, email, display_name, avatar, role, department, "
            "security_clearance, tenant_id, created_at, updated_at "
            "FROM users WHERE email = ?",
            (email,),
        ).fetchone()

        if not row:
            return None

        return User(
            firebase_uid=row[0], email=row[1], display_name=row[2],
            avatar=row[3], role=row[4], department=row[5],
            security_clearance=row[6], tenant_id=row[7],
            created_at=row[8], updated_at=row[9],
        )

    def close(self):
        self.conn.close()
