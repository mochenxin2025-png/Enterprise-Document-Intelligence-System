# EDIS 框架技术栈与模块组成

> v1.2 — 面向非技术读者的完整说明

---

## 零、一句话概述

EDIS 是一个**企业文档智能问答系统**。你把 PDF、Word、Markdown 等工程文档丢进去，它用 AI 读懂后存起来，之后你可以像问同事一样用自然语言提问，系统会从文档中找到答案，并标注答案来自哪一页。

整个过程**不需要联网服务**（除了最终回答问题时调用一次大模型），所有数据都留在你自己的电脑上。

---

## 一、整体技术栈（一句话版）

| 层    | 用的是什么                                   | 通俗解释                    |
| ---- | --------------------------------------- | ----------------------- |
| 编程语言 | **Python 3.10+**                        | 就像盖房子用的砖                |
| 数据库  | **SQLite**（单文件）                         | 一个文件就是整个数据库，不用装 MySQL   |
| 向量存储 | **sqlite-vec**（SQLite 插件）               | 让 SQLite 能存"语义指纹"并快速比对  |
| 文档解析 | **PyMuPDF**（PDF）+ **python-docx**（Word） | 把文件内容读出来                |
| 文字识别 | **PaddleOCR**（图片里的字）                    | 把扫描件/图片里的文字提取出来         |
| 语义理解 | **BGE-large-zh-v1.5**（本地 CPU 运行）        | 把文字变成"语义指纹"（1024 个数字组成） |
| 大模型  | **DeepSeek API**（回答问题）                  | 最终生成答案的大脑               |
| 图像理解 | **MiniMax API**（看懂图片）                   | 回答关于图片/图表的问题            |
| 包管理  | **uv**（快速安装）                            | 比 pip 快 10 倍的包安装工具      |
| 对外接口 | **MCP 协议**（标准接口）+ **CLI**（命令行）          | 让其他 AI 助手也能调用 EDIS      |

---

## 二、完整技术栈（详细版）

```
┌──────────────────────────────────────────────────────────────┐
│                      接入层 (Access Layer)                    │
│  MCP Server (JSON-RPC)    │    CLI (命令行)    │   Python SDK │
├──────────────────────────────────────────────────────────────┤
│                    安全层 (Security Layer)                    │
│  L1 租户隔离 → L2 权限控制 → L3 检索前过滤 → L4 二次校验 → L5 审计 │
├──────────────────────────────────────────────────────────────┤
│                    认证层 (Auth Layer)                        │
│  AuthManager → JWT(HS256) / Firebase / Local(pbkdf2+bcrypt)  │
├──────────────────────────────────────────────────────────────┤
│                    业务层 (Business Layer)                    │
│  QAEngine v3.2 → IntentClassifier → Reranker → ContextBuilder│
├──────────────────────────────────────────────────────────────┤
│                    检索层 (Retrieval Layer)                   │
│  VectorStore(sqlite-vec) + ParentDocRetrieval + Hybrid(BM25)  │
├──────────────────────────────────────────────────────────────┤
│                    数据层 (Data Layer)                        │
│  Parser(6种) → Cleaner(5步) → Chunker → Embedder(BGE 1024d)  │
├──────────────────────────────────────────────────────────────┤
│                    存储层 (Storage Layer)                     │
│  SQLite + sqlite-vec    │    本地文件系统    │   modelscope    │
└──────────────────────────────────────────────────────────────┘
```

---

## 三、模块组成与接口说明

### 1. 核心引擎模块 (`qa/engine.py`)

**归属：** 业务层 — 整个系统的大脑，编排所有步骤。

**通俗理解：** 就像餐厅的主厨，接到客人点单（问题）后，指挥各环节：先去储藏室找食材（检索文档），检查食材是否新鲜（权限校验），然后烹饪（调用大模型生成答案），最后端出去（返回答案+来源标注）。

**技术栈：** Python · DeepSeek API · 自实现 Reranker · ContextBuilder · PromptRegistry

**对外接口（QAEngine）：**

| 方法 | 参数 | 作用 | 无后端知识能否理解 |
|---|---|---|---|
| `ask(question)` | 问题文本 | 基础问答（单路检索） | ✅ 输入问题→得到答案 |
| `ask_v2(question, user_context)` | 问题 + 用户身份 | 增强问答（含权限过滤、父文档检索、精排、审计） | ✅ 同上，但加了权限控制 |

---

### 2. 文档解析模块 (`plugins/__init__.py` + `parsers/`)

**归属：** 数据层 — 把各种格式的文件"翻译"成系统能理解的纯文本。

**通俗理解：** 就像一个万能翻译官，不管你给的是 PDF、Word、Markdown、HTML 还是纯文本，都能提取出里面的文字内容。OCR 还能"看懂"扫描件里的字。

**技术栈：** PyMuPDF · python-docx · PaddleOCR · beautifulsoup4

**支持的格式（ParserInterface）：**

| 解析器 | 格式 | 依赖 | 通俗理解 |
|---|---|---|---|
| `pymupdf` | PDF | PyMuPDF（内置） | 读 PDF 文件 |
| `docx` | Word | python-docx | 读 Word 文档 |
| `markdown` | .md | Python 标准库 | 读 Markdown |
| `html` | 网页 | bs4（可选） | 读网页文件 |
| `text` | TXT/CSV/JSON | Python 标准库 | 读纯文本 |
| `ocr` | 图片 | PaddleOCR（可选） | 识别图片里的文字 |

**注册新解析器的方法：** `@PluginRegistry.register("parser", "格式名")`

---

### 3. 数据清洗模块 (`cleaning/`)

**归属：** 数据层 — 把解析出的原始文本中的垃圾内容去掉。

**通俗理解：** PDF 解析出来的文字经常夹杂着页眉页脚、页码、乱码、多余空格。清洗模块就像一个文字编辑，把这些"噪音"删掉，只保留真正有用的内容。

**技术栈：** Python 标准库 · chardet（编码检测）

**清洗步骤：**
1. 编码检测与统一（UTF-8）
2. 多余空白清理
3. 特殊字符规范化
4. 垃圾内容质量打分
5. OCR 后处理（全角→半角转换）

**质量分级：** `clean`（干净）→ `noisy`（有噪声）→ `unreadable`（不可读）

---

### 4. 文本分块模块 (`ingestion/chunker.py`)

**归属：** 数据层 — 把长文档切成小段。

**通俗理解：** 一篇 300 页的手册不能整本丢给 AI 去理解（太长了）。分块模块就像把一本书按章节撕成小卡片，每张卡片大小适中，AI 一次只看几张卡就能找到答案。

**技术栈：** Python 标准库

**分块策略（HierarchicalChunker）：**
- 优先按文档自带的标题/章节结构切分
- 每块默认 768 字符，重叠 128 字符（防止关键信息卡在边界）
- 大文档（>100页）自动并行处理

---

### 5. 语义向量模块 (`retrieval/__init__.py` — Embedder 类)

**归属：** 检索层 — 把文字变成"语义指纹"。

**通俗理解：** 你搜"苹果手机"和"iPhone"字面完全不同，但说的是同一回事。向量模块能把任何一段文字变成 1024 个数字组成的"语义指纹"，意思相近的文本指纹也相近。有了指纹，搜索就不是简单的关键词匹配，而是理解意思。

**技术栈：** PyTorch · Transformers · BGE-large-zh-v1.5（1024维）

**为什么不用更流行的 sentence-transformers？** 因为 Hermes 沙箱环境下会死锁。所以直接用底层 transformers 库 + 自己实现 mean pooling。

**接口（EmbeddingInterface）：**

| 方法 | 作用 |
|---|---|
| `encode(texts)` | 把一批文本变成向量 |
| `encode_query(query)` | 把问题变成向量（自动加检索前缀） |
| `dimension` | 返回维度（1024） |

---

### 6. 向量存储与检索模块 (`retrieval/__init__.py` — VectorStore 类)

**归属：** 检索层 — 存"语义指纹"并快速找到最相似的。

**通俗理解：** 想象一个巨大的指纹库，每张文档卡片都有一个语义指纹。你提问题时，系统先算出问题的指纹，然后在这个库里找指纹最接近的那些卡片。这就是"语义搜索"——不是搜关键词，而是搜意思。

**技术栈：** SQLite · sqlite-vec（L2 距离）

**接口（VectorStore）：**

| 方法 | 作用 | 无后端知识能否理解 |
|---|---|---|
| `insert_document(...)` | 记录一个文档 | ✅ 往库里加书 |
| `insert_chunk(...)` | 存入一个文本片段 | ✅ 往书里加卡片 |
| `insert_embedding(...)` | 存入语义指纹 | 把卡片按上指纹 |
| `search(embedding, top_k, tenant_id, user_context)` | 找最相似的 K 个卡片 | ✅ 按指纹找卡片 |
| `search_with_parent_retrieval(...)` | 找到相关卡片后，把整本书的卡片都拉出来 | ✅ 找到线索后翻全书 |
| `get_document_chunks(...)` | 取出某文档的全部卡片 | ✅ 把整本书的卡片全拿出来 |

**约束：** 当前使用全表扫描（无 ANN 近似索引），百万级 chunk 会变慢。适合中小规模（<10万 chunk）。

---

### 7. 精排模块 (`adapters/reranker.py`)

**归属：** 检索层 — 对搜索结果再次排序，把真正有用的排前面。

**通俗理解：** 初次搜索找到了 20 张卡片，但排序可能不准——摘要卡片排第一，真正答案在第五。精排模块根据关键词匹配、内容多样性、页码位置等因素重新排序，确保最有用的卡片排前面。

**技术栈：** Python 标准库（启发式）/ DeepSeek API（LLM 精排）

**两种实现（RerankerInterface）：**

| 实现 | 原理 | 成本 |
|---|---|---|
| `HeuristicReranker` | 关键词重叠 + 多样性 + 位置加权 | 零成本（默认） |
| `LLMReranker` | 让大模型直接选出最相关的片段 | 有 token 成本 |

**接口：**

| 方法 | 作用 |
|---|---|
| `rerank(query, candidates, scores, pages)` | 返回重新排序后的索引列表 |

---

### 8. 问答引擎流程（完整链路）

```
用户提问 "MQTT如何配置？"
        │
        ▼
   [QA Pair 缓存] ──命中→ 直接返回（跳过后续步骤）
        │ 未命中
        ▼
   [意图识别] —— 判断是"参数查询"还是"操作步骤"
        │
        ▼
   [语义指纹计算] —— 把问题变成 1024 个数字
        │
        ▼
   [父文档检索] —— 先找相关卡片，再拉整本书
        │
        ▼
   [精排 Rerank] —— 重新排序，关键词匹配的排前面
        │
        ▼
   [融合去重] —— 去掉重复内容，检测矛盾信息
        │
        ▼
   [L4 权限校验] —— 确认用户有权看这些内容
        │
        ▼
   [上下文组装] —— 裁剪到 token 预算内
        │
        ▼
   [大模型生成] —— DeepSeek 根据上下文写答案
        │
        ▼
   [L5 输出脱敏] —— 去掉身份证/手机号等敏感信息
        │
        ▼
   [审计日志] —— 记录谁问了什么、看了哪些文档
        │
        ▼
   返回：答案 + 引用来源 [文档名, Page X]
```

---

### 9. 安全五层架构

| 层级 | 模块文件 | 做什么 | 通俗理解 |
|---|---|---|---|
| **L1 租户隔离** | `config/tenant.py` | 不同企业数据互相看不到 | 不同公司的资料库完全隔离 |
| **L2 权限控制** | `permissions/__init__.py` | 同一公司内按角色/部门/密级控制访问 | 机密文件只有管理层能看到 |
| **L3 检索前过滤** | `retrieval/__init__.py`（search 方法） | 只在自己有权限的范围内搜索 | 搜索前就划定范围，不会搜到不该看的东西 |
| **L4 生成前校验** | `verifier/__init__.py` | 检索结果在喂给 AI 前再次检查 | 最后一道门禁，防止"搜到了但已无权看" |
| **L5 审计日志** | `audit/__init__.py` | 记录每次问答的完整链路 | 谁在什么时候问了什么、看了哪些文档 |

**三种访问策略：**

| 策略 | 含义 |
|---|---|
| `open` | 租户内所有人可见（默认） |
| `role_based` | 需匹配角色或部门 |
| `whitelist` | 仅指定用户白名单 |

**四级密级：** 0=公开 · 1=内部 · 2=机密 · 3=绝密

---

### 10. 认证模块 (`auth/`)

**归属：** 认证层 — 管理用户身份。

**通俗理解：** 就像公司门禁卡——先验证你是谁，再根据你的身份决定你能看什么。

**技术栈：** Python 标准库 · bcrypt（密码哈希）· Firebase Admin SDK（可选）

| 文件 | 职责 | 通俗理解 |
|---|---|---|
| `auth/models.py` | User 模型 + SQLite 存储 | 用户档案表 |
| `auth/jwt_service.py` | JWT 令牌签发/验证 | 登录后发一张"电子通行证"，之后凭通行证操作 |
| `auth/providers.py` | Firebase + Local 认证 | 支持 Firebase 登录（前端用）或本地账号密码（CLI 用） |
| `auth/__init__.py` | AuthManager 统一入口 | 前台，统一对外 |

**接口（AuthManager）：**

| 方法 | 作用 |
|---|---|
| `login(provider, credential)` | 登录 → 返回用户信息 + JWT |
| `register(provider, email, password, name)` | 注册新用户 |
| `verify_jwt(token)` | 验证通行证是否有效 |
| `get_user(uid)` | 查用户信息 |

---

### 11. 对外接口模块

#### MCP Server (`mcp_server.py`)

**归属：** 接入层 — 让其他 AI 助手（如 Claude Desktop、Cursor）能调用 EDIS。

**通俗理解：** EDIS 本身没有聊天界面，但它提供一个标准接口，任何兼容 MCP 协议的 AI 助手都能接上来使用。

**技术栈：** JSON-RPC 2.0 · stdio 通信

**对外工具（9个）：**

| 工具 | 参数 | 作用 | 无后端知识能否理解 |
|---|---|---|---|
| `edis_ask` | question, user_id | 向知识库提问 | ✅ 问问题 |
| `edis_search` | query, top_k | 语义搜索（不调大模型） | ✅ 搜文档 |
| `edis_ingest` | filepath | 导入文档 | ✅ 上传文件 |
| `edis_status` | — | 查看系统状态 | ✅ 看统计 |
| `edis_compare` | entity_a, entity_b | 比较两个实体 | ✅ 对比 |
| `edis_citations` | topic | 查找引用来源 | 找引用 |
| `edis_evaluate` | dataset_path | 运行评估 | 自动测试 |
| `edis_category` | text | 检测文档类别 | ✅ 识别类型 |
| `edis_audit` | limit | 查询审计日志 | 查看操作记录 |

#### CLI 命令 (`main.py`)

```bash
# 导入文档
python main.py ingest "D:/docs/manual.pdf"

# 提问
python main.py --v2 ask "MQTT如何配置？"

# 带身份认证的提问
python main.py --token <jwt> --v2 ask "控制阀规格？"

# 用户管理
python main.py auth register --email alice@corp.com --password xxx
python main.py auth login --email alice@corp.com --password xxx
python main.py auth whoami --token <jwt>
```

---

### 12. 支撑模块速查

| 模块 | 文件 | 一句话 |
|---|---|---|
| 接口抽象 | `interfaces/` | 定义了 6 种"插座"规范，任何符合规范的"插头"都能用 |
| 配置管理 | `config/` + `config.yaml` | 所有设置集中管理 |
| 上下文组装 | `context_builder/` | 把检索到的卡片拼成 AI 能理解的格式 |
| 提示词模板 | `config/prompts.py` | 7 种提问模板，根据意图自动选择 |
| 知识补丁 | `qa_pairs/` | 人工预置的问答对，命中则直接返回（不走 AI） |
| 待答队列 | `unanswered/` | AI 答不了的问题收集起来，人工补充 |
| 文档分类 | `config/categorizer.py` | 自动识别文档属于哪个领域（工程机械/光通信等） |
| 成本追踪 | `operations/` | 统计每次大模型调用花了多少钱 |
| 本体知识 | `ontology/` | 单位换算（mW↔dBm）、别名识别（ONU=光网络单元） |
| 文件安全 | `security.py` | 文件上传校验 + 注入攻击防护 + 频率限制 |
| 评估系统 | `evaluate.py` | 自动测试 Recall、Faithfulness 指标 |
| 大模型适配 | `plugins/__init__.py` | 已注册：DeepSeek、OpenAI、MiniMax |
| 语义嵌入适配 | `plugins/__init__.py` | 已注册：BGE-large-zh-v1.5 |

---

## 四、底层约束（为什么要这样设计）

| 约束 | 原因 |
|---|---|
| SQLite 而非 MySQL/PostgreSQL | 零运维、单文件备份、不需要装数据库服务 |
| sqlite-vec 全表扫描（无 ANN 索引） | 当前阶段数据量不大（<10万 chunk），全表扫描可接受 |
| 不用 sentence-transformers | Hermes 沙箱环境下导入会死锁，必须用底层 transformers |
| BGE 而非 OpenAI Embedding | 本地免费、数据不出境、1024 维够用 |
| modelscope 下载模型 | GFW 无法访问 HuggingFace |
| CPU 推理而非 GPU | 用户机器是 AMD 消费级显卡，无 CUDA |
| Embedding 维度锁定 1024 | 一旦确定不可更改，否则旧数据全部失效（属于数据库 Schema） |
| 权限过滤在检索前（Filter First） | 不给模型看到无权数据，永远不会泄露 |
| Python 3.10+ | 项目兼容性基准 |
| uv 而非 pip | 更快、更可靠、更好的依赖锁定 |

---

## 五、整体"口感"总结

如果你完全不懂后端：

- **EDIS 就像一个智能图书管理员**。你把书（文档）给它，它读懂后存到自己的书架（数据库）里。
- 你问它问题时，它先翻书架找到相关的书和页码（检索），确认你有权看这些内容（权限），然后把相关内容整理好（上下文组装），最后请一个专家（大模型）根据这些内容写出答案。
- 整个过程**自动记录谁看了什么**（审计），答案会**自动遮挡身份证/手机号等隐私信息**（脱敏），不同公司的资料**完全隔离**（租户）。

用一句话概括：**把你的工程文档变成可以对话的知识库，安全、可追溯、零外部依赖。**
