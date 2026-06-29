# EDIS 企业级 RAG 安全升级报告

> **项目**: Enterprise Document Intelligence System (EDIS)  
> **升级范围**: v1.0 → v1.1 — 五层企业级权限架构落地  
> **测试**: 26 → 47 (+21) — 全部通过  
> **日期**: 2026-06-29

---

## 一、总体对比

| 维度 | 升级前 (v1.0) | 升级后 (v1.1) |
|---|---|---|
| **测试覆盖** | 26 个单元测试 | **47 个测试** (26 原有 + 21 新增) |
| **L1 租户隔离** | 部分实现（表有 tenant_id 列） | ✅ **全面覆盖** — 检索/QA/状态查询均强制过滤 |
| **L2 文档/Chunk 权限** | ❌ 不存在 | ✅ **完整实现** — 7+5 权限列 + 三种访问策略 + 四级密级 |
| **L3 检索前过滤** | ❌ 全库检索后无过滤 | ✅ **Filter First** — SQL 层下推权限条件 |
| **L4 生成前校验** | ❌ 不存在 | ✅ **PermissionVerifier** — 租户/密级/策略/角色二次验证 |
| **L5 审计日志** | ❌ 不存在 | ✅ **AuditLogger** — 全链路追踪 + 输出脱敏 |
| **MCP Tools** | 8 个 | **9 个** (+ `edis_audit`) |
| **代码模块** | 26 个 | **29 个** (+ `permissions/`, `verifier/`, `audit/`) |

---

## 二、五层架构逐层对比

### L1 — 租户隔离

| 对比项 | 升级前 | 升级后 |
|---|---|---|
| `VectorStore.search()` | 无 tenant 过滤 — 全库混查 | `WHERE c.tenant_id = ?` |
| `QARegistry.list_all()` | 全局列出所有租户 QA | `WHERE tenant_id = ?` |
| `tool_status()` | 全局统计 | 按租户统计 |
| Bug: 同 question 跨租户覆盖 | `INSERT OR REPLACE` 覆盖不同租户的同 ID 行 | hash 加入 `tenant_id:` 前缀 |

### L2 — 文档/Chunk 权限

| 对比项 | 升级前 | 升级后 |
|---|---|---|
| documents 表权限字段 | 无 | role, department, project, user_whitelist, security_level, document_owner, access_policy (7 列) |
| chunks 表权限字段 | 无 | role, department, project, security_level, access_policy (5 列，继承自文档) |
| 访问策略 | 无 | open / role_based / whitelist 三种 |
| 密级控制 | 无 | 0=public, 1=internal, 2=confidential, 3=secret |
| Schema 迁移 | 无 | 自动 ALTER TABLE（幂等） |

### L3 — 检索前过滤 (Filter First)

| 对比项 | 升级前 | 升级后 |
|---|---|---|
| 检索流程 | 全库向量检索 → TopK → 无过滤 | **权限过滤 → 向量检索** |
| SQL 过滤 | 无 | `PermissionManager.build_sql_filter()` 生成 WHERE 子句 |
| QAEngine 透传 | `search()` 无 user_context | `ask_v2(question, user_context={...})` |

### L4 — 生成前二次校验

| 对比项 | 升级前 | 升级后 |
|---|---|---|
| 检索后验证 | 无 | `PermissionVerifier.verify_batch()` |
| 租户一致性检查 | 无 | chunk.tenant_id vs user.tenant_id |
| 密级复核 | 无 | chunk.security_level vs user.security_clearance |
| 角色/部门匹配 | 无 | role_based 策略验证 |
| 文档存在性检查 | 无 | DB 反查确认文档未删除 |

### L5 — 审计日志与输出控制

| 对比项 | 升级前 | 升级后 |
|---|---|---|
| 审计日志 | 无 | `audit_log` 表 — 16 字段全链路记录 |
| 日志内容 | 无 | user_id, question, 检索文档, 引用 chunk, 答案, 置信度, 意图, 模型, 延迟, 安全告警, 时间戳 |
| 输出脱敏 | 无 | 身份证/手机号/邮箱/IP 自动脱敏 |
| MCP 审计查询 | 无 | `edis_audit` 工具 |
| 审计统计 | 无 | `AuditLogger.stats()` — total_queries, avg_confidence, avg_latency, security_alerts |

---

## 三、新增文件清单

| 文件 | 说明 |
|---|---|
| `permissions/__init__.py` | PermissionManager + build_sql_filter() + validate_access() |
| `verifier/__init__.py` | PermissionVerifier — L4 生成前二次校验 |
| `audit/__init__.py` | AuditLogger — L5 审计日志 |

## 四、修改文件清单

| 文件 | 改动 |
|---|---|
| `retrieval/__init__.py` | Schema 迁移、insert_document/chunk 加权限、search() 加 tenant+user_context 过滤 |
| `qa/engine.py` | 集成 L4 校验 + L5 审计 + 输出脱敏 |
| `qa/__init__.py` | 同步 tenant 传播 |
| `qa_pairs/__init__.py` | list_all() 租户过滤、hash 加 tenant_id 前缀 |
| `unanswered/__init__.py` | hash 加 tenant_id 前缀 |
| `tools/__init__.py` | tool_status() 租户过滤、+tool_audit() |
| `mcp_server.py` | tool_status() 租户过滤、tool_ask() 加 user_id + security_alerts、+edis_audit |
| `main.py` | main() 入口、ingest_pdf() 权限继承 |
| `setup.py` | 修复 entry_points |
| `tests/test_core.py` | +21 测试 (L1: 5 + L2: 8 + L4: 5 + L5: 3) |

---

## 五、安全原则对照

| 设计原则 | 实现状态 |
|---|---|
| «不给模型看到，就不会泄露» | ✅ L3 Filter First — 权限过滤在检索前执行 |
| «Chunk 永远不能成为脱离权限控制的孤立数据» | ✅ L2 — Chunk 继承文档全部权限字段 |
| «Filter First, Retrieve Second» | ✅ `search(user_context=...)` — SQL WHERE 下推 |
| «权限服务负责最终确认» | ✅ L4 PermissionVerifier — 生成前二次验证 |
| «检索阶段防止拿错，生成阶段防止说错» | ✅ L5 输出脱敏 + 审计追溯 |

---

## 六、测试覆盖分布

```
原有测试: 26 (Plugin + Interface + Parser + QA Pair + Queue + Clean + Ontology + Chunker + Category)
Phase 1:   +5 (TenantIsolation)
Phase 2:   +8 (Permissions: schema + insert + inherit + search + filter + validate)
Phase 3:   +8 (PermissionVerifier: 5 + AuditLogging: 3)
─────────────────
总计:      47 tests — 100% pass
```
