"""多租户隔离层 — 所有数据查询统一加 tenant_id 过滤

设计:
  - 单 SQLite 文件，tenant_id 列隔离
  - Ontology 全局共享（工程术语通用）
  - retrieval/qa_pairs/queue/memory/cross_document 均隔离
"""
from contextlib import contextmanager
from threading import local

# 当前请求的租户上下文（线程安全）
_tenant_ctx = local()


def set_current_tenant(tenant_id: str):
    """设置当前线程的租户上下文"""
    _tenant_ctx.value = tenant_id


def get_current_tenant() -> str:
    """获取当前线程的租户，默认 'default'"""
    return getattr(_tenant_ctx, 'value', 'default')


@contextmanager
def tenant_context(tenant_id: str):
    """with tenant_context('client_a'): ..."""
    old = get_current_tenant()
    set_current_tenant(tenant_id)
    try:
        yield
    finally:
        set_current_tenant(old)


# ── SQL 辅助 ───────────────────────────────────

def tenant_filter(table_alias: str = "") -> str:
    """生成 WHERE tenant_id = ? 子句"""
    col = f"{table_alias}.tenant_id" if table_alias else "tenant_id"
    return f"{col} = ?"


def tenant_params() -> tuple:
    """返回当前租户的参数元组"""
    return (get_current_tenant(),)


def with_tenant(sql: str, table_alias: str = "") -> tuple[str, tuple]:
    """在 SQL 末尾追加 tenant 过滤"""
    if "WHERE" in sql.upper():
        final = f"{sql} AND {tenant_filter(table_alias)}"
    else:
        final = f"{sql} WHERE {tenant_filter(table_alias)}"
    return final, tenant_params()
