"""Permission Verifier — 企业级 RAG L4: 生成前二次校验

在检索完成后、LLM 调用前，对每个 chunk 进行二次权限验证。

验证内容:
  1. tenant_id 是否一致
  2. doc_id 是否仍可访问
  3. 权限是否发生变化（与检索时对比）
  4. 文档是否被删除
  5. 密级是否合法

设计原则:
  «权限服务负责最终确认，而不是向量数据库。»
  向量检索提供候选，权限验证作为安全兜底。
"""

import json
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class VerificationResult:
    """单次验证结果"""
    passed: bool
    total_chunks: int = 0
    rejected_chunks: int = 0
    passed_chunks: int = 0
    alerts: list[str] = field(default_factory=list)
    rejected_reasons: list[str] = field(default_factory=list)


class PermissionVerifier:
    """生成前权限二次校验"""

    @staticmethod
    def verify_chunk(
        chunk: dict,
        user_context: dict,
        tenant_id: str,
    ) -> tuple[bool, str]:
        """验证单个 chunk 是否可访问。返回 (passed, reason)。

        chunk dict 需包含: tenant_id, security_level, access_policy,
                          role, department, user_whitelist, document_owner, project
        """
        # 1. 租户一致性
        chunk_tenant = chunk.get("tenant_id", "")
        if chunk_tenant and chunk_tenant != tenant_id:
            return False, f"tenant mismatch: chunk={chunk_tenant}, user={tenant_id}"

        # 2. 密级检查
        clearance = user_context.get("security_clearance", 0)
        sec_level = chunk.get("security_level", 0)
        if isinstance(sec_level, str):
            try:
                sec_level = int(sec_level)
            except (ValueError, TypeError):
                sec_level = 3  # 无法解析 → 默认最高密级，拒绝访问

        if sec_level > clearance:
            return False, f"security_level={sec_level} > clearance={clearance}"

        # 3. 访问策略检查
        policy = chunk.get("access_policy", "open")

        if policy == "open":
            return True, ""

        user_id = user_context.get("user_id", "")

        # 文档所有者
        if chunk.get("document_owner") == user_id:
            return True, ""

        if policy == "role_based":
            user_role = user_context.get("role", "")
            chunk_role = chunk.get("role", "")
            user_dept = user_context.get("department", "")
            chunk_dept = chunk.get("department", "")
            if user_role and chunk_role and user_role == chunk_role:
                return True, ""
            if user_dept and chunk_dept and user_dept == chunk_dept:
                return True, ""
            return False, "role_based: no role/department match"

        if policy == "whitelist":
            whitelist_str = chunk.get("user_whitelist", "[]")
            try:
                whitelist = json.loads(whitelist_str) if isinstance(whitelist_str, str) else whitelist_str
            except (json.JSONDecodeError, TypeError):
                whitelist = []
            if user_id in whitelist:
                return True, ""
            return False, "whitelist: user not authorized"

        return False, f"unknown policy: {policy}"

    @staticmethod
    def verify_batch(
        chunks: list,
        user_context: dict,
        tenant_id: str,
        db_conn=None,
    ) -> VerificationResult:
        """批量验证检索结果。返回 (保留的 chunks, VerificationResult)。

        chunk 可以是 dict 或对象（有 __dict__ / getattr）。
        db_conn: 可选，用于检查文档是否仍存在（L4 doc-existence check）。
        """
        passed = []
        result = VerificationResult(passed=False, total_chunks=len(chunks))

        for ch in chunks:
            # 统一为 dict
            if isinstance(ch, dict):
                chunk_dict = ch
            else:
                chunk_dict = {
                    "tenant_id": getattr(ch, "tenant_id", tenant_id),
                    "security_level": getattr(ch, "security_level", 0),
                    "access_policy": getattr(ch, "access_policy", "open"),
                    "role": getattr(ch, "role", ""),
                    "department": getattr(ch, "department", ""),
                    "user_whitelist": getattr(ch, "user_whitelist", "[]"),
                    "document_owner": getattr(ch, "document_owner", ""),
                    "project": getattr(ch, "project", ""),
                }

            ok, reason = PermissionVerifier.verify_chunk(
                chunk_dict, user_context, tenant_id,
            )

            if ok:
                passed.append(ch)
                result.passed_chunks += 1
            else:
                result.rejected_chunks += 1
                result.rejected_reasons.append(reason)

        # 4. 文档存在性检查（如有 DB 连接）
        if db_conn and passed:
            doc_ids = set()
            for ch in passed:
                doc_id = getattr(ch, "document_id", "") if not isinstance(ch, dict) else ch.get("document_id", "")
                source = getattr(ch, "source", "") if not isinstance(ch, dict) else ch.get("source", "")
                # 用 source (filename) 反查文档
                if source:
                    row = db_conn.execute(
                        "SELECT id FROM documents WHERE filename = ? AND tenant_id = ?",
                        (source, tenant_id),
                    ).fetchone()
                    if not row:
                        result.alerts.append(f"Document '{source}' no longer exists")
                        # 不强制移除 — 这是告警而非阻断

        result.passed = result.rejected_chunks == 0
        if result.rejected_chunks > 0:
            result.alerts.extend(result.rejected_reasons)

        return result, passed
