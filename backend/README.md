# ODMFlow Backend

ODMFlow 是面向 Android 手机与平板 ODM 场景的对话式业务 Agent。它将产品与定制咨询、需求评估、本人订单查询和售后申请集中到私人对话中，结合企业知识检索与受控业务操作，减少资料查找和重复沟通。

后端采用模块化单体架构：Agent 负责理解请求、编排任务和调用能力，业务模块负责权限、规则与状态流转，数据访问由各模块的存储实现承接。

## 核心能力

- **持久对话**：注册登录、私人会话与消息历史、流式回复、失败保底消息及执行记录。
- **任务编排**：将复杂请求拆为有限任务，按依赖执行；校验参数、能力范围与风险等级，限制修复、重试和循环次数。
- **知识检索**：本地知识库支持向量、BM25 和 RRF 混合召回，返回来源引用及可展开的检索记录。
- **记忆管理**：同会话近期消息与较早内容摘要，以及用户级结构化偏好画像。
- **业务闭环**：本人订单与售后查询、模拟订单及售后确认卡，用户确认后执行，支持取消和状态查询。

## 快速启动

以下命令均在**后端根目录（包含 `pyproject.toml`）**执行，示例使用 PowerShell；Linux/macOS 复制模板时可使用 `cp`。不要直接运行测试配置来启动服务。

### 1. 环境与配置

需要 Python 3.14、[uv](https://docs.astral.sh/uv/) 和 MySQL 8.0.16+。完整聊天还需要支持结构化输出的 OpenAI 兼容 Chat API；仅有 Chat API 即可，本地 RAG 的 Embedding 另行准备。外部模型调用可能按量收费。

```powershell
uv sync --locked
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
if (-not (Test-Path application.toml)) {
    Copy-Item application.toml.example application.toml
}
```

填写实际 `.env`，不要用模板占位值连接服务：

| 配置                                                                 | 填写内容                                                                                                |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `ODMFLOW_DATABASE_URL`                                               | `mysql+pymysql://USER:PASSWORD@HOST:3306/DATABASE`；使用自己的项目账号和库，凭证中的 URL 特殊字符需编码 |
| `ODMFLOW_MODE` / `ODMFLOW_APP_ORIGIN`                                | 本地设 `local` 与 `http://127.0.0.1:5173`，须与浏览器前端来源一致                                       |
| `ODMFLOW_LLM_MODEL` / `ODMFLOW_LLM_API_KEY` / `ODMFLOW_LLM_BASE_URL` | 模型名、Key 和服务商 API Base URL；远端使用 HTTPS，本地回环地址允许 HTTP                                |
| `ODMFLOW_CONFIG_FILE`                                                | 源码运行使用 `application.toml`；非源码部署使用实际文件的绝对路径                                       |
| `ODMFLOW_RAG_ROOT` / `ODMFLOW_TRACE_DEBUG_ENABLED`                   | RAG 资源绝对路径与执行详情开关；RAG 关闭时无需准备资源，调试默认关闭                                    |

`application.toml` 管理超时、任务预算、记忆与检索策略，初次可保留模板默认值。模型上下文窗口应按服务商能力调整，不要超过实际限制。配置修改后重启后端；应用不会自动加载 `.env`，下方命令通过 `--env-file` 显式加载。

### 2. 创建数据库并执行迁移

先启动 MySQL。使用管理员在 **MySQL 客户端或数据库 GUI 的 SQL 窗口**中创建新空库，并为项目专用账号授权：

```sql
CREATE DATABASE odmflow CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
```

`odmflow` 是可修改的示例库名，需与 `.env` 一致；已有项目库不要重复建库。迁移账号需要该库的建表和结构修改权限。

回到**后端终端**执行：

```powershell
uv run --locked --env-file .env python -m alembic upgrade head
uv run --locked --env-file .env python -m alembic current
uv run --locked --env-file .env python -m alembic heads
```

`current` 与 `heads` 应一致。Alembic 完整迁移链负责首次建表与后续升级，不需要独立初始化 SQL。不要单独运行 `migrations/env.py`，也不要删除 `migrations/versions/`。迁移不创建 MySQL 数据库、数据库账号或应用登录账号，不填充默认订单。

后续更新结构仍执行 `upgrade head`，升级已有业务库前先备份。MySQL DDL 可能隐式提交；失败时先排查实际结构和权限，不盲目 `stamp head` 或删除数据库。

### 3. 启动与验证

```powershell
uv run --locked --env-file .env uvicorn odmflow.main:app --host 127.0.0.1 --port 8000
```

开发时可追加 `--reload`；服务应持续运行，按 Ctrl+C 停止。另开终端启动前端，再在页面注册、登录，不提供共享默认账号。

- [健康接口](http://127.0.0.1:8000/health)：应返回 `{"status":"ok"}`，仅证明服务进程存活。
- [Swagger](http://127.0.0.1:8000/docs)：接口文档，不是聊天前端。
- 前端登录后发送问候，验证真实模型回复；刷新后检查会话消息是否保留。

模型缺项时 Agent 返回 503，身份功能仍可单独使用；健康接口正常不代表数据库、模型或 RAG 已就绪。API 兼容声明不保证所有模型都能正确规划任务，需使用实际服务商验证。

## RAG 初始化（可选）

默认 `application.toml` 的 `[rag]` 中 `enabled = false`。先跑通聊天再启用 RAG；不需要部署独立向量服务或本地 Chat 大模型。

### 1. 准备本地 Embedding 资源

安装可选依赖：

```powershell
uv sync --locked --extra rag
```

创建独立资源目录，在 `.env` 中填写 `ODMFLOW_RAG_ROOT` 的绝对路径，按下面结构准备文件：

```text
<RAG资源根>/
└── models/bge-small-zh-v1.5-onnx/
    ├── MODEL-MANIFEST.json
    ├── model_optimized.onnx
    ├── config.json
    ├── ort_config.json
    ├── special_tokens_map.json
    ├── tokenizer.json
    ├── tokenizer_config.json
    └── vocab.txt
```

从 [Qdrant 的固定 ONNX 版本](https://huggingface.co/Qdrant/bge-small-zh-v1.5/tree/46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59)下载上述模型与 tokenizer 文件，不要下载 Git LFS 指针文本代替权重。将 [模型清单模板](knowledge/model-manifest.example.json) 复制到该目录并命名为 `MODEL-MANIFEST.json`。

当前适配器固定支持 `BAAI/bge-small-zh-v1.5` 的这份 512 维 ONNX 文件，CPU 推理；文件版本与 SHA-256 由清单及代码校验。不能只改清单就更换任意模型。服务不会自动下载，清单也不是模型权重。

### 2. 构建并验证索引

仍在后端根目录执行：

```powershell
uv run --locked --extra rag --env-file .env python -m odmflow.knowledge.cli build
uv run --locked --extra rag --env-file .env python -m odmflow.knowledge.cli search "售后需要准备哪些材料" --mode hybrid --top-k 3
```

默认原文来自 [knowledge/corpus](knowledge/corpus/)。模型缓存、Chroma 快照和构建产物写入资源根的 `cache/`、`indexes/`、`artifacts/`，不写入源码仓库。资料或模型变化后显式重新构建；索引签名不匹配时不会偷偷混用。

### 3. 开启在线检索

在现有 `application.toml` 的 `[rag]` 下修改，不要重复添加同名分组：

```toml
enabled = true
retrieval_mode = "hybrid"
candidate_k = 10
top_k = 3
rrf_constant = 60
```

停止原服务，再使用带 `rag` extra 的命令启动：

```powershell
uv run --locked --extra rag --env-file .env uvicorn odmflow.main:app --host 127.0.0.1 --port 8000
```

登录后询问“平板无法开机，申请售后需要准备哪些材料？”，检查检索事件与来源。需要查看候选排名、距离和注入片段时，在实际 `.env` 中启用 `ODMFLOW_TRACE_DEBUG_ENABLED=true` 并重启；对外部署保持关闭。

## 技术架构

Python 3.14、FastAPI、Pydantic、LangChain / LangGraph、SQLAlchemy、MySQL 与 Alembic。可选知识检索使用 FastEmbed 本地 Embedding、进程内 Chroma 与 BM25；确认流程使用 SQLite checkpoint，不需要独立 checkpoint 服务。

| 模块                                                                        | 职责                                                       |
| --------------------------------------------------------------------------- | ---------------------------------------------------------- |
| [main.py](src/odmflow/main.py)                                              | 应用组合根：装配服务、注册路由、管理生命周期与全局异常     |
| [agent](src/odmflow/agent/)                                                 | 流式入口、任务图、能力目录、运行上下文、执行记录与确认子图 |
| [identity](src/odmflow/identity/)                                           | 账号、登录 Session、身份解析与 CSRF 防护                   |
| [conversations](src/odmflow/conversations/)                                 | 会话归属、消息持久化、历史查询与轮次状态                   |
| [profiles](src/odmflow/profiles/)                                           | 用户偏好画像的提取、读取、修改与删除                       |
| [knowledge](src/odmflow/knowledge/)                                         | 离线知识库构建、切分与向量化、在线召回和评测               |
| [inquiries](src/odmflow/inquiries/)                                         | ODM 需求字段、缺失项与冲突规则                             |
| [orders](src/odmflow/orders/) / [after_sales](src/odmflow/after_sales/)     | 本人订单与售后业务规则、查询及存储                         |
| [business_actions](src/odmflow/business_actions/)                           | 待确认申请、版本与有效期校验、幂等提交及业务结果           |
| [persistence](src/odmflow/persistence/)                                     | SQLAlchemy 数据库连接与 Session 基础设施                   |
| [configuration](src/odmflow/configuration/) / [system](src/odmflow/system/) | 分类配置加载与系统健康接口                                 |
| [migrations](migrations/)                                                   | Alembic 完整迁移链，负责首次建表与后续结构升级             |

HTTP 层处理协议与身份，应用服务组织用例，业务模块执行规则，存储实现访问数据库。Agent 不直接拼装 SQL，也不通过模型提供的用户 ID 决定数据归属。

## 请求与执行链路

```text
登录 Session → 身份与会话校验 → 用户消息提交 MySQL
  → 准备同会话记忆与用户画像
  → 任务识别 → 计划校验 → 选择可执行任务
  → 调用受控能力 → 记录结果 → 检查进度
  → 继续任务 / 有限重规划 / 汇总回答
  → 流式输出 → 回复、来源与最终状态提交 MySQL
```

主流程使用显式 LangGraph 任务图，不是让模型无限循环调用工具。模型提出意图、任务与参数，服务端决定允许执行的能力和终止条件；知识检索按任务需要执行，问候不要求经过 RAG。

流式入口为 `POST /agent/turns/stream`；会话与历史查询属于 `/conversations`。数据库短事务在线程池中执行并等待结果：用户消息保存成功后才运行模型，最终保存成功后才发送完成事件，不采用无确认的后台写入。

需要确认的申请进入独立子图：准备确认卡 → interrupt 等待用户 → 确认或取消 → 校验并执行 → 保存结果。等待期间不要求保持 SSE 长连接。恢复时重新核验登录身份、归属、版本与有效期；确认不等于重新运行整轮聊天。

## 数据与配置归属

| 载体                                                 | 内容与边界                                                                      |
| ---------------------------------------------------- | ------------------------------------------------------------------------------- |
| MySQL                                                | 账号、Session、会话消息、摘要、画像、订单、售后、待确认动作与执行记录的业务事实 |
| Chroma                                               | 企业资料片段及向量；BM25 从同一知识快照建立关键词索引                           |
| SQLite checkpoint                                    | 确认子图的恢复状态与动作引用；不替代 MySQL 业务库                               |
| 单轮运行上下文                                       | 本轮加载的记忆、检索证据、工具结果与运行依赖；不是另一份长期数据存储            |
| [.env.example](.env.example)                         | 环境配置模板：数据库连接、模型服务与密钥、资源路径等                            |
| [application.toml.example](application.toml.example) | 分类策略模板：超时、执行预算、检索、摘要、画像与确认流程                        |

实际配置、模型权重、向量索引及运行数据库不进入版本管理。Alembic 连接已创建的 MySQL 数据库完成建表或升级，应用启动不会自动执行迁移。

## 部署要点

当前支持单进程部署，未提供 Docker Compose 或多实例协调配置。基础运行命令不等于生产环境已完成安全加固。

- 使用进程管理器保持服务运行；部署时不加 `--reload`，维持一个 worker。启用 RAG 时保留 `--extra rag`。
- 由 HTTPS 网关提供前端和同源 `/api` 转发，移除 `/api` 前缀后到达后端；允许 POST 流式响应，关闭 SSE 缓冲，代理读取超时覆盖整轮运行预算。
- 对外部署设置 `ODMFLOW_MODE=production`，`ODMFLOW_APP_ORIGIN` 填前端的实际 HTTPS origin，生产 Session Cookie 使用 Secure。不要把本地模式暴露到公网。
- 模型 Key、连接串只放后端环境；前端不可持有。实际 `.env`、`application.toml` 不提交，公开环境关闭详细调试并补充网关限流、访问控制和日志治理。
- 持久化 MySQL、RAG 资源与 `approvals.checkpoint_path` 指定的 SQLite 文件；checkpoint 父目录需可写，不随更新清空。MySQL 保存业务事实，SQLite 保存确认子图恢复状态。
- 备份数据库和持久化目录，升级前执行迁移并核对版本；服务启动不会自动建表。等待用户确认无需一直维持流式连接。

## 常见问题

| 现象                             | 优先检查                                                                               |
| -------------------------------- | -------------------------------------------------------------------------------------- |
| 前端 502                         | 后端进程是否持续运行、8000 端口以及前端开发代理目标                                    |
| 未登录时 `GET /auth/me` 返回 401 | 正常身份探测，不是服务启动失败                                                         |
| 登录提示 `Origin not allowed`    | 浏览器来源与 `ODMFLOW_APP_ORIGIN` 是否完全一致，勿混用 localhost 与 127.0.0.1          |
| 数据库操作失败或申请卡不可读     | MySQL 连接/权限，以及 `alembic current` 是否达到 `heads`                               |
| Agent 503                        | Chat 配置或会话存储是否可用；不要只看 `/health`                                        |
| 模型超时                         | 服务商可用性、`model.request_timeout_seconds`、`agent.turn_timeout_seconds` 与代理超时 |
| 没有 RAG 或索引不可用            | extra、资源绝对路径、固定模型、索引构建及 `rag.enabled`，并检查启动日志                |

## 能力边界

订单与售后为模拟业务，不涉及真实支付、退款或物流；知识资料为合成 ODM 场景资料，不代表真实企业的价格、产能或承诺。涉及写入的操作必须经过受控确认，身份与归属校验始终由服务端执行。

当前长期记忆以结构化用户画像为主，未实现私人经历的向量记忆。执行面板展示任务、工具与检索的可观测记录，不展示模型内部思维链。本地资源与 checkpoint 按单进程部署设计，多实例协调和生产运维仍需另行建设。
