"""Permission Manager — 企业级 RAG L2: 文档/Chunk 权限控制

设计原则:
  - 权限与 Embedding 解耦：权限变化不需重新索引
  - Chunk 继承文档权限：切块不丢失权限
  - Filter First, Retrieve Second：检索前过滤而非检索后

安全等级:
  0 = public (公开)
  1 = internal (内部)
  2 = confidential (机密)
  3 = secret (绝密)

访问策略:
  open       — 所有租户成员可访问
  role_based — 需要匹配角色/部门
  whitelist  — 仅白名单用户
"""

import json
from dataclasses import dataclass, field
from typing import Optional


# ── Constants ───────────────────────────────────

SECURITY_LEVELS = {
    0: "public",
    1: "internal",
    2: "confidential",
    3: "secret",
}

ACCESS_POLICIES = ["open", "role_based", "whitelist"]


# ── Permission Manager ──────────────────────────

class PermissionManager:
    """构建权限过滤条件 + 验证访问权限"""

    @staticmethod
    def default_permissions(
        owner: str = "",
        role: str = "",
        department: str = "",
        project: str = "",
        security_level: int = 1,
        access_policy: str = "open",
        user_whitelist: list[str] = None,
        **overrides,
    ) -> dict:
        """创建标准权限字典"""
        p = {
            "role": role,
            "department": department,
            "project": project,
            "security_level": security_level,
            "document_owner": owner,
            "access_policy": access_policy,
            "user_whitelist": user_whitelist or [],
        }
        p.update(overrides)
        return p

    @staticmethod
    def build_sql_filter(
        user_context: dict,
        table_alias: str = "c",
    ) -> tuple[str, list]:
        """构建 SQL WHERE 子句 + 参数，仅返回用户有权访问的数据。

        user_context = {
            "user_id": "alice",
            "role": "engineer",
            "department": "R&D",
            "project_ids": ["proj-a", "proj-b"],
            "security_clearance": 2,   # 用户最高可访问密级
        }

        Returns: (where_clause, params) 例如 ("(c.access_policy='open' OR ...)", [...])
        """
        params = []
        conditions = []

        clearance = user_context.get("security_clearance", 0)

        # open 策略：所有租户成员可访问
        conditions.append(f"{table_alias}.access_policy = 'open' AND {table_alias}.security_level <= ?")
        params.append(clearance)

        # role_based 策略：角色或部门匹配
        role = user_context.get("role", "")
        dept = user_context.get("department", "")
        if role or dept:
            cond = f"{table_alias}.access_policy = 'role_based' AND {table_alias}.security_level <= ?"
            role_params = [clearance]
            if role:
                cond += f" AND {table_alias}.role = ?"
                role_params.append(role)
            if dept:
                cond += f" AND {table_alias}.department = ?"
                role_params.append(dept)
            conditions.append(f"({cond})")
            params.extend(role_params)

        # whitelist 策略：用户在文档白名单中
        user_id = user_context.get("user_id", "")
        if user_id:
            # user_whitelist 是 JSON 数组，用 LIKE 匹配
            conditions.append(
                f"({table_alias}.access_policy = 'whitelist' AND "
                f"{table_alias}.security_level <= ? AND "
                f"{table_alias}.user_whitelist LIKE ?)"
            )
            params.append(clearance)
            params.append(f'%"{user_id}"%')

        # 文档所有者始终可访问
        if user_id:
            conditions.append(f"({table_alias}.document_owner = ?)")
            params.append(user_id)

        # project 过滤（如果指定了 project_ids）
        project_ids = user_context.get("project_ids", [])
        if project_ids:
            proj_conds = []
            for pid in project_ids:
                proj_conds.append(f"{table_alias}.project = ?")
                params.append(pid)
            conditions.append(f"({' OR '.join(proj_conds)})")

        where = "(" + " OR ".join(conditions) + ")"
        return where, params

    @staticmethod
    def validate_access(
        chunk_row: dict,
        user_context: dict,
    ) -> bool:
        """同步验证：给定 chunk 行和用户上下文，判断是否有权访问。

        chunk_row 至少包含: access_policy, security_level, role, department,
                          user_whitelist, document_owner, project
        """
        policy = chunk_row.get("access_policy", "open")
        sec_level = chunk_row.get("security_level", 0)
        clearance = user_context.get("security_clearance", 0)

        if sec_level > clearance:
            return False

        if policy == "open":
            return True

        if policy == "owner" or chunk_row.get("document_owner") == user_context.get("user_id"):
            return True

        if policy == "role_based":
            user_role = user_context.get("role", "")
            chunk_role = chunk_row.get("role", "")
            user_dept = user_context.get("department", "")
            chunk_dept = chunk_row.get("department", "")
            if user_role and chunk_role and user_role == chunk_role:
                return True
            if user_dept and chunk_dept and user_dept == chunk_dept:
                return True
            return False

        if policy == "whitelist":
            user_id = user_context.get("user_id", "")
            whitelist_str = chunk_row.get("user_whitelist", "[]")
            try:
                whitelist = json.loads(whitelist_str) if isinstance(whitelist_str, str) else whitelist_str
            except (json.JSONDecodeError, TypeError):
                whitelist = []
            return user_id in whitelist

        return False


# ── Convenience ─────────────────────────────────

def inherit_permissions(doc_permissions: dict) -> dict:
    """Chunk 继承文档权限字段（去掉 user_whitelist 和 document_owner，chunk 不需要）"""
    return {
        "role": doc_permissions.get("role", ""),
        "department": doc_permissions.get("department", ""),
        "project": doc_permissions.get("project", ""),
        "security_level": doc_permissions.get("security_level", 1),
        "access_policy": doc_permissions.get("access_policy", "open"),
    }
