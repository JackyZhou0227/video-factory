# Video Factory 单机版升级维护清单

> 文档用途：维护单台 Windows 主机通过内网穿透提供小规模公网服务时的安全、稳定和可维护性事项。
>
> 优先级评分：10 分为必须优先处理；1 分为低优先级。评分同时考虑安全影响、数据影响、被公网利用的可能性和修复前置关系。
>
> 状态约定：`[ ]` 未开始，`[-]` 进行中，`[x]` 已完成，`[~]` 暂缓或不适用。

## 当前运行假设

- 主机：一台 Windows PC，应用保持单进程、单 Uvicorn worker。
- 规模：最多约 50 个账号，日常约 20 人使用，峰值有效并发预计不超过 10。
- 瓶颈：Qwen-TTS、FFmpeg、RunningHub 和磁盘空间，而不是数据库吞吐量。
- 目标：先让功能灵活可用、部署简单、出问题可恢复，不提前建设 SaaS 级基础设施。
- 数据原则：任务、输出、配置、BGM 和模板继续按现有边界保护；音色库按公共资源设计，不强制用户隔离。

## 当前目标

- [-] 让服务可以安全地通过花生壳等内网穿透暴露到公网。
- [-] 支持小规模多用户使用，重点保证任务、输出文件、配置和管理权限边界。
- [x] 在不改变业务行为的前提下，引入 SQLAlchemy 2.x 和 Alembic，先保持 SQLite 运行；三个 Store 已全部迁移并统一数据库入口。
- [x] ORM 层稳定后，把生产数据库从 SQLite 迁移到 PostgreSQL。生产 `DATABASE_URL` 已强制 PostgreSQL（psycopg），Engine 拒绝非 PostgreSQL 连接，Alembic 已有 0001~0004 迁移链。
- [~] 暂不引入 Redis、独立任务队列、多 worker 和 pgvector；这些仍按实际需求决定。
- [-] 限制公网用户对 CPU、GPU、内存、磁盘、第三方 API 和 FFmpeg 的消耗。
- [-] 建立可备份、可恢复、可升级的 Windows 单机运行方式。

## 单机版决策原则

- PostgreSQL 和 ORM 是确定的技术路线，但采用“先 ORM + SQLite，再切 PostgreSQL”的两阶段迁移。
- ORM 迁移阶段保持现有表、字段、用户权限和业务返回内容不变，不顺便重构所有业务模型。
- SQLite 在迁移期间继续作为可运行后端；先解决备份、文件清理、写入错误和恢复流程。
- 公共音色库允许所有登录用户查看、试听、使用、新增、修改和删除；按公共资源设计，不做用户隔离。
- 任务产物继续放在任务目录，`artifacts_json` 暂不拆表；只有明确需要时再拆分。
- 用进程内信号量、现有任务表和配置项控制并发与配额；暂不新增每日用量统计表。
- Redis、独立队列、多 worker 和 pgvector 仍由真实运行需求触发，不与 ORM/ PostgreSQL 迁移绑定。

## 优先级总览

| 分数 | 含义 | 处理建议 |
|---:|---|---|
| 10 | 公网前阻断项，可能导致接管、越权、密钥泄露或直接拒绝服务 | 第一批修复 |
| 9 | 高风险项，可能造成严重资源滥用、数据泄露或生产不稳定 | 公网前完成或明确缓解措施 |
| 8 | 重要架构项，影响后续扩展、恢复和维护成本 | 与数据库/公网改造同步 |
| 7 | 中高优先级工程项，影响长期稳定性和排障效率 | 第一版公网运行后尽快完成 |
| 6 | 一般增强项，提升规范性、可维护性和体验 | 按迭代安排 |
| 5 及以下 | 优化项或远期能力 | 有实际需求再做 |

## 一、身份认证与权限

### AUTH-01 禁止公开注册或改为邀请制 — 10 分

- 状态：`[x]`
- 当前问题：`POST /api/auth/register` 对公网开放；首个真实用户可能自动成为管理员。
- 涉及文件：`web-app/app/api/auth.py`、`web-app/app/services/auth_store.py`
- 改造方向：
  - 增加 `security.registration_enabled` 配置，生产默认关闭。
  - 首次初始化只允许本机执行。
  - 新用户由管理员创建，或使用一次性邀请码。
  - 禁止“第一个公网注册用户自动成为管理员”。
- 验收标准：关闭注册后，公网调用返回明确拒绝；管理员初始化流程仍可用；没有任何竞态可以抢占管理员角色。

### AUTH-02 删除固定默认管理员密码 — 10 分

- 状态：`[x]`
- 当前问题：`init_default_admin.bat` 和 README 中存在 `admin / 12345678`。
- 涉及文件：`web-app/init_default_admin.bat`、`README.md`、`web-app/scripts/init_admin.py`
- 改造方向：删除脚本中的固定密码；支持交互式输入，或自动生成随机密码并只显示一次；初始化完成后强制修改密码；立即轮换已有部署中的管理员密码。
- 验收标准：仓库中不再出现固定生产密码；初始化命令行参数不会把密码长期暴露在脚本和文档中。

### AUTH-03 登录限流和暴力破解防护 — 10 分

- 状态：`[x]`
- 当前问题：登录接口没有 IP/账号维度限流、失败锁定或异常登录记录。
- 涉及文件：`web-app/app/api/auth.py`、`web-app/app/services/auth_store.py`
- 改造方向：按 IP 和用户名分别统计失败次数；连续失败后短暂延迟或锁定；对登录、注册、密码修改接口设置独立限流；记录成功/失败时间、IP、User-Agent 和原因；单机第一版可使用数据库，用户量增大后再引入 Redis。
- 验收标准：暴力尝试不会无限消耗 PBKDF2/CPU；正常用户不会因单个 IP 的攻击而全部无法登录。

### AUTH-04 Cookie、Session 和 HTTPS 安全加固 — 10 分

- 状态：`[x]`
- 当前状态：Cookie 的 `Secure`、`HttpOnly`、`SameSite` 和有效期已配置化，并能识别花生壳转发的 HTTPS；改密后撤销该用户全部 Session、禁用用户时撤销其会话、过期 Session 定时清理（5 分钟间隔）均已实现。
- 涉及文件：`web-app/app/api/auth.py`、`web-app/app/services/auth_store.py`
- 下一步：补充独立的“登出其他设备/管理员强制下线（不禁用账号）”端点。
- 验收标准：HTTP 访问不会发送生产 Session；密码或账号状态变化后旧 Session 不能继续使用；过期 Session 不会持续增长。

### AUTH-05 CSRF 防护 — 10 分

- 状态：`[-]`
- 当前状态：已实现双提交 CSRF Cookie、`X-CSRF-Token` 校验和前端自动附加 Header；生产配置示例已启用。还可以补充 Origin/Referer 校验和真实公网浏览器验证。
- 涉及范围：所有 `POST`、`PUT`、`PATCH`、`DELETE` 接口。
- 下一步：通过花生壳 HTTPS 域名验证文件上传、登出、任务创建、设置修改和管理员操作均能正常通过 CSRF 校验。
- 验收标准：第三方站点无法借助用户已有 Cookie 执行任务、改密码、改 API Key 或删除资源。

### AUTH-06 密码管理能力补齐 — 8 分

- 状态：`[x]`
- 当前状态：普通用户可以在“设置”页通过旧密码修改自己的密码；修改成功后该用户的所有已有 Session（包括当前设备）都会失效，需要重新登录。
- 改造方向：增加旧密码校验的修改密码接口；密码修改后撤销该用户其他 Session；最低长度提升到 12 位或提供 12 位推荐；拒绝常见密码、用户名和明显重复密码；面向外部用户前再引入邮箱验证/找回流程。
- 验收结果：已实现旧密码校验、最小长度校验、拒绝重复密码、密码更新和全量 Session 撤销，并补充接口回归测试。

### AUTH-07 公共音色库与资源权限 — 9 分

- 状态：`[~]`
- 决策：音色库是公司维护的公共资源，不做写权限收紧。所有登录用户都可以新增、修改和删除公共音色；不再按管理员限制维护权限。
- 任务、产物、配置、BGM 和用户模板仍必须按现有用户边界校验。
- 后续若出现私有音色或误删风险，再增加 `visibility`、`owner_id` 或删除确认机制，不提前为公共音色库引入隔离复杂度。
- 验收标准：用户 A 不能访问用户 B 的任务、产物、配置和私有资源。

### AUTH-08 管理员操作审计 — 5 分

- 状态：`[~]`
- 单机版先使用结构化日志记录关键管理员操作，不立即新增审计表。
- 需要记录：密码重置、角色变化、用户创建/禁用、API Key 修改、音色维护和任务删除。
- 当管理员数量、用户规模或合规要求上升时，再新增 `audit_events` 表。
- 验收标准：关键操作至少能从日志追溯操作者、目标、时间和结果。

### DATA-01 引入 SQLAlchemy 2.x — 9 分

- 状态：`[x]`
- 结论：纳入确定路线，但先只做持久化层替换，不改变业务功能。
- 第一阶段建立 SQLAlchemy Engine、Session、Base Models 和数据库访问适配层；现有 Store 逐步迁移，避免一次性重写。
- 首批按现有结构映射 `users`、`sessions`、`settings`、`subtitle_replacements`、`bgm_tracks` 和 `generation_tasks`。
- 暂不把公共音色 JSON、模板文件和任务产物 JSON 强行塞进数据库。
- 已完成：新增 SQLAlchemy Engine、Session、Base Models 和数据库访问适配层；`settings_store`、`auth_store`、`task_store` 已全部切换到 ORM，并通过共享的 `app.db.engine`/`app.db.session` 使用同一个 `DATABASE_URL`、Engine 缓存和 Session factory；非 SQLite 数据库跳过旧 schema 自动初始化，PostgreSQL schema 生命周期由 Alembic 管理。
- 验收标准：SQLite 现有数据可继续登录、创建任务、查询任务、读取配置和访问 BGM；业务 API 不出现行为回归。当前后端全量测试 161 个通过。

### DATA-02 引入 Alembic 数据库迁移 — 9 分

- 状态：`[x]`
- ORM 引入时同步建立 Alembic，先为现有 SQLite 数据库制作 baseline migration。
- 禁止继续依赖应用启动时无版本地执行未知结构变更；后续表结构变化必须有版本号和升级说明。
- baseline 前先核对真实数据库与代码 schema 的差异，包括当前发现的 `bgm_tracks.loudness` 字段漂移。
- 已完成：新增 `alembic.ini`、迁移环境和 `0001` baseline；新 SQLite 可 `upgrade head`，现有 SQLite 已备份后 `stamp 0001`，并通过 `alembic check`。
- 验收标准：新 SQLite 环境可从零迁移；已有数据库可安全标记版本；后续迁移失败有备份和回滚路径。

### DATA-03 SQLite 迁移到 PostgreSQL — 8 分

- 状态：`[x]`
- 已完成：`DATABASE_URL`/`database.url` 强制 PostgreSQL（psycopg），新增 `scripts/migrate_sqlite_to_postgres.py` 一次性导入脚本与迁移记录文档。
- 结论：纳入路线，但必须在 SQLAlchemy + Alembic + SQLite 适配稳定后进行，不与 ORM 重写同时硬切。
- 新增 `DATABASE_URL` 配置，保留 SQLite 作为开发和回滚后端一段时间。
- 编写一次性 SQLite → PostgreSQL 导入和核对脚本，迁移 users、sessions、settings、tasks、BGM 等现有数据。
- 保留用户 ID、任务 ID、时间、密码哈希、JSON 内容和文件相对路径；文件本身继续留在文件系统。
- 验收标准：迁移后用户可登录，历史任务可查询，产物和 BGM 可访问，关键表行数和外键关系核对一致。

### DATA-04 设计 PostgreSQL 模型和约束 — 8 分

- 状态：`[x]`
- 已完成：现有表结构已按保守映射迁入 PostgreSQL，业务语义未变。
- 第一版按现有 SQLite 业务结构做保守映射，不借迁移机会大规模重构。
- 公共音色库仍按公共资源设计；如果将来把音色索引迁入 PostgreSQL，不默认增加 `user_id` 隔离，可记录 `created_by`、`updated_by`、`status` 和 `is_builtin`。
- `generation_tasks.artifacts_json` 第一阶段继续保留；`task_artifacts`、`user_usage_daily`、私有音色等属于后续独立需求。
- 在 PostgreSQL 中补齐外键、唯一约束和必要索引，但不改变现有 API 的业务语义。
- 验收标准：数据库约束增强后，现有前端和任务流程无需修改即可运行。

### DATA-05 PostgreSQL 连接池和 Session 生命周期 — 8 分

- 状态：`[x]`
- 已完成：Engine 统一管理连接，`pool_size`/`max_overflow`/`pool_timeout`/`pool_pre_ping` 已配置化。
- ORM 引入后统一由 Engine 管理连接；SQLite 阶段保持保守连接配置，不为了低并发做复杂调优。
- PostgreSQL 阶段使用单进程、短生命周期 Session 和小连接池，建议先从 `pool_size=3`、`max_overflow=2`、`pool_pre_ping=true` 起步，再根据指标调整。
- 长时间 GPU、FFmpeg、RunningHub 和 TTS 任务不得持有数据库连接或事务。
- 验收标准：并发不超过当前规模时无连接泄漏、长事务和数据库锁等待；迁移 PostgreSQL 后能观察连接池等待和事务耗时。

### DATA-06 pgvector 预留 — 2 分

- 状态：`[~]`
- PostgreSQL 迁移后保留扩展安装方式，但不增加向量字段和运行时依赖。
- 真正出现知识库、RAG 或素材语义搜索需求时，再建立独立 embedding 表和索引。

### DEPLOY-01 应用只监听本机回环地址 — 10 分

- 状态：`[x]`
- 当前问题：示例配置和启动脚本使用 `0.0.0.0:18888`。
- 涉及文件：`web-app/config.example.yaml`、`web-app/start_app.bat`、`web-app/main.py`
- 改造方向：应用监听 `127.0.0.1:18888`；花生壳只转发到本机回环地址；Windows 防火墙禁止外部直接访问 18888；禁止通过路由器端口映射绕过花生壳安全策略。
- 验收标准：局域网其他机器无法直接访问应用端口；公网只能通过配置好的隧道入口访问。

### DEPLOY-02 生产模式关闭 reload — 10 分

- 状态：`[x]`
- 当前问题：`web-app/main.py:17` 使用 `reload=True`，可能导致模型重复加载、显存占用增加和任务状态异常。
- 改造方向：开发启动脚本保留 reload；生产启动脚本明确关闭 reload；使用固定 Python/Conda 环境启动，不依赖系统默认 `python`。
- 验收标准：生产进程只有一个明确的应用进程；重启和升级行为可预测。

### DEPLOY-03 HTTPS、反向代理和 Host 校验 — 9 分

- 状态：`[-]`
- 改造方向：公网入口必须使用 HTTPS；配置可信 Host 白名单；正确处理代理传递的协议和客户端 IP；不允许任意 Origin、任意 Host 或任意 CORS 配置。
- 验收标准：异常 Host 被拒绝；公网浏览器只通过 HTTPS 建立登录会话；日志中能区分真实客户端 IP 和隧道代理 IP。

### DEPLOY-04 安全响应头和 CORS 收敛 — 7 分

- 状态：`[x]`
- 当前问题：当前 CORS 仅允许本地开发地址，但方法和请求头允许范围较宽。
- 改造方向：生产只允许实际前端 Origin；不使用 `allow_origins=["*"]` 配合 Cookie；增加 CSP、`X-Content-Type-Options`、`Referrer-Policy`、`Permissions-Policy` 等响应头。
- 验收标准：生产前端、开发前端和未知来源的跨域行为符合预期。

## 四、资源消耗、上传和任务执行

### RESOURCE-01 统一上传大小和格式限制 — 10 分

- 状态：`[x]`
- 当前问题：多个接口直接 `await upload.read()` 全量读入内存，部分接口没有统一大小限制和实际文件格式验证。
- 重点文件：`web-app/app/api/digital_human.py`、`poster_video.py`、`template_production.py`、`tts_studio.py`、`web-app/app/services/voice_profiles.py`
- 改造方向：统一流式保存上传文件；限制单文件大小、单请求总大小和用户总容量；校验扩展名、MIME 和文件头/实际格式；对音频、图片、视频设置不同限制；失败时清理临时文件。
- 验收标准：超大文件在写满内存/磁盘前被拒绝；伪造扩展名不能绕过格式限制。

### RESOURCE-02 用户配额和全局并发限制 — 9 分

- 状态：`[x]`
- 已完成：`generation_tasks` 继续作为持久化事实来源，`pending` 表示已接纳等待、`running` 表示正在执行；创建前按 `pending/running` 统计校验 `tasks.max_running_tasks_per_user`（默认 3），全局接纳上限自动等于 `max_active_jobs + max_queued_jobs`（默认 10 + 8 = 18），超额统一返回 429。
- 已完成：进程内 `TaskExecutionManager` 以 `max_active_jobs`（默认 10）和 `max_queued_jobs`（默认 8）限制业务任务执行与排队；FFmpeg/Pillow/ZIP 等阻塞本地工作共用与全局任务池相同数量的线程，Qwen 线程池直接使用 `tts.qwen3_tts_base.concurrent_limit`，并与模型自身信号量共同限制本地模型工作。
- 已完成：认证后的 `/api/tasks/summary` 和侧栏“任务中心”显示用户/全局的等待、运行、合计及上限，并展示本机、媒体、Qwen 槽位占用。
- 已完成：磁盘低水位保护随 RESOURCE-04 一并实现——`storage_cleanup.enforce_disk_space` 在任务创建前校验输出目录所在磁盘，低于 `tasks.disk.min_free_bytes`（默认 5 GiB）或 `min_free_percent`（默认 5%）时返回 429；RunningHub 远端任务的可取消轮询仍按实际需求决定。
- 单机版方案：不新增每日用量表；后续规模扩大后，再考虑 `user_usage_daily` 或 Redis。
- 验收标准：单个账号无法独占 GPU、CPU、磁盘或第三方 API 额度。

### RESOURCE-03 任务执行从进程内后台任务升级 — 5 分

- 状态：`[-]`
- 已完成：单机版继续使用进程内后台运行时，但不再裸用无界默认线程池；四类后台任务通过受生命周期管理的有界队列调度，应用启动将遗留 `pending/running` 标记失败，避免任务状态长期悬挂。
- 待补充：最大运行时间、用户取消接口与 FFmpeg 子进程的协作终止；不立即引入 Redis 或独立 worker。
- 触发条件：需要多 worker/多主机、任务恢复成为刚需，或单机队列无法满足业务时，再评估独立队列。
- 验收标准：重启后任务不会伪装成运行中；用户可以看到等待、运行和失败状态并重新提交。

### RESOURCE-04 输出文件、临时文件和磁盘清理 — 9 分

- 状态：`[x]`
- 已完成：新增 `app/services/storage_cleanup.py`，提供孤儿任务目录扫描（以 `generation_tasks.storage_path` 集合精确比对）、遗留 `.part` 临时文件清理和失败/取消任务目录按保留期清理（默认 7 天，保留数据库记录并将 artifacts 置空、message 标注“产物已过期清理”）；BGM 孤儿与音色库文件仅报告不自动删除。
- 已完成：清理任务在应用启动后延迟 5 分钟首跑、此后每日执行一次（lifespan 内 asyncio 周期循环，文件操作放线程）；管理员可通过 `GET /api/admin/storage/report` 和 `POST /api/admin/storage/cleanup`（默认 dry_run）手动扫描和清理；`/api/tasks/summary` 返回磁盘状态。
- 已完成：磁盘低水位保护——低于 `tasks.disk.min_free_bytes` / `min_free_percent` 时拒绝创建新任务（429），不影响运行中和排队中任务。
- 配置项：`tasks.cleanup.enabled / orphan_retention_days / failed_task_retention_days`、`tasks.disk.min_free_bytes / min_free_percent`。
- 保留策略数据库表未建，符合“单机版不立即建设复杂保留策略表”的约定；数据库、公共音色目录、用户输出目录、配置文件和模型路径仍需纳入备份清单（OPS-03）。
- 验收标准：连续运行不会无限增长磁盘；清理不会误删其他用户或公共音色文件。

### RESOURCE-05 外部服务和模型调用超时/重试 — 8 分

- 状态：`[x]`
- 已完成：RunningHub、LLM、Qwen-TTS 的 HTTP 调用均已设置显式超时；失败清理与有限重试按各服务现状覆盖。
- 单机版继续补齐各外部服务的超时、失败清理和有限重试；暂不引入复杂熔断平台。
- 验收标准：第三方服务异常不会长期占用任务、连接和 GPU；用户能看到可理解的失败原因。

### RESOURCE-06 限制 LLM Base URL，防止 SSRF — 10 分

- 状态：`[x]`
- 已完成：LLM 出站地址默认拒绝回环、私网、链路本地、保留、多播等地址，并有配套测试。
- 当前问题：用户可以提交任意 HTTP/HTTPS LLM 地址，服务端会代为请求。
- 改造方向：普通用户不能自由设置 Base URL，或只允许管理员白名单；拒绝 localhost、回环、私网、链路本地和云元数据地址；禁止自动跟随跳转到不允许的地址；对 DNS 解析后的 IP 重新校验，避免 DNS rebinding。
- 验收标准：公网用户不能借助 LLM 测试接口探测公司内网或访问本机管理服务。

## 五、密钥、数据和隐私

### SECRET-01 API Key 安全存储 — 9 分

- 状态：`[-]`
- 当前状态：API Key 仍以明文存库，`is_secret` 只是标记；展示侧已有掩码（`api_key_masked`），`extra_info` 敏感字段过滤已实现；加密存储、DPAPI/Credential Manager 和日志脱敏尚未实现。
- 改造方向：限制数据库文件和备份权限；禁止 Key 出现在日志、异常、任务 extra_info 和前端返回值；Windows 部署优先使用 DPAPI 或 Windows Credential Manager；数据库只保存密钥引用或加密密文。
- 验收标准：数据库备份、普通日志和接口响应中无法直接获得可用 API Key。

### SECRET-02 配置和密钥轮换 — 8 分

- 状态：`[-]`
- 当前状态：RunningHub/LLM 的 Key 更新与撤销（清空重置）流程已实现；配置变更审计日志尚未实现。
- 改造方向：提供 API Key 修改和撤销流程；明确旧任务是否继续使用旧 Key；为 RunningHub、LLM、PostgreSQL 分别记录配置变更审计；文档、脚本、示例配置不包含真实密钥和默认密码。
- 验收标准：密钥泄露后可以快速替换，不需要手工修改多处文件。

### DATA-RETENTION-01 数据保留和隐私策略 — 7 分

- 状态：`[ ]`
- 单机版先明确参考音频、公共音色、上传素材、生成结果和失败任务的保留时间。
- 先通过定时清理脚本和管理员操作完成，不新增数据保留策略表。
- 删除任务时同步处理输出目录；删除公共音色前需要管理员确认并保留备份策略。
- 验收标准：磁盘不会无限增长，用户能知道自己的上传素材和生成结果会保留多久。

### OPS-01 生产启动和进程托管 — 9 分

- 状态：`[-]`
- 当前状态：`start.bat` 生产脚本已固定 production 环境、关闭 reload，并含 Python/依赖/前端构建/端口占用的启动前检查；Windows 进程托管（服务/计划任务自动拉起）和日志轮转尚未实现。
- 使用固定 Python/Conda 环境，生产关闭 reload，Windows 重启后自动启动并在异常退出时拉起。
- 启动前检查配置、模型目录、FFmpeg、SQLite、输出目录和显卡状态。
- 日志先按日期或大小轮转，不引入复杂监控平台。
- 验收标准：Windows 重启后服务可以按预期恢复；启动失败有明确诊断信息。

### OPS-02 健康检查和就绪检查 — 6 分

- 状态：`[-]`
- 当前状态：已有 `/api/health` 基础存活端点；尚未区分 liveness/readiness，也未检查数据库、输出目录、FFmpeg 和模型状态。
- 单机版增加简单的 liveness/readiness 区分：进程存活、数据库可读写、输出目录可写、FFmpeg 可用、模型状态可用。
- 不检查 PostgreSQL，也不在健康接口泄露内部路径、版本或密钥。
- 验收标准：花生壳或 Windows 监控可以区分“进程活着”和“服务能接任务”。

### OPS-03 数据库和文件备份 — 9 分

- 状态：`[ ]`
- 当前重点不是 PostgreSQL 备份，而是 SQLite 数据库、配置、公共音色目录、用户输出目录和模型配置的备份。
- 先提供 Windows 定时备份脚本，保留多个版本，并至少做一次恢复演练。
- 备份中不得包含可公开泄露的文档密码；真实 API Key 需要单独保护。
- 验收标准：可以在同一台或另一台 Windows 主机恢复用户、任务记录、公共音色和关键配置。

### OPS-04 错误日志和敏感信息脱敏 — 8 分

- 状态：`[ ]`
- 改造方向：区分用户错误、业务失败、第三方失败和系统异常；客户端只返回通用错误；服务端日志保留 traceback 但脱敏 Token、API Key、Cookie、密码和绝对路径；为任务 ID、用户 ID、请求 ID 建立关联日志。
- 验收标准：单次请求可以从日志追踪到任务，但日志不包含可用凭证。

### OPS-05 依赖锁定和漏洞扫描 — 8 分

- 状态：`[ ]`
- 当前问题：Python 依赖主要使用宽松的 `>=` 版本约束。
- 改造方向：锁定 Python 生产依赖版本；区分 GPU/CUDA 依赖和通用依赖；定期运行 Python 依赖漏洞扫描和前端依赖审计；更新前验证 FastAPI、Pydantic、SQLAlchemy、PyTorch、qwen-tts、FFmpeg 兼容性。
- 验收标准：可以复现生产环境；依赖升级有记录、有回滚方案。

## 七、测试与质量保障

### TEST-01 认证和权限测试补齐 — 10 分

- 状态：`[x]`
- 已覆盖：未登录访问、管理员权限、任务/产物/BGM/模板边界、登录限流、CSRF 失败、默认管理员初始化、注册关闭、改密后旧 Session 撤销、组织越权拦截、上传限制、LLM 内网地址拦截和 Key 不泄露。
- 当前 `tests/` 下共 23 个测试文件、161 个测试用例，高风险权限边界均有自动化测试覆盖。
- 验收标准：每个高风险权限边界都有自动化测试，不能只依赖手工验证。

### TEST-02 PostgreSQL 集成测试 — 2 分

- 状态：`[~]`
- 生产数据库已是 PostgreSQL，但尚未建立真实 PostgreSQL 集成测试；当前仍以单元测试为主，需尽快补齐真实库迁移和并发事务测试。

### TEST-03 上传和资源滥用测试 — 9 分

- 状态：`[x]`
- 改造方向：测试超大文件、超多文件、错误 MIME、伪造扩展名、并发创建任务、重复提交、任务重启恢复、磁盘不足、FFmpeg 超时、模型加载失败和第三方服务不可用。
- 验收标准：异常输入不会导致进程崩溃、内存失控、任务永久卡住或越权读取。

### TEST-04 公网部署冒烟测试 — 8 分

- 状态：`[ ]`
- 改造方向：通过实际花生壳 HTTPS 域名测试登录、Cookie、上传、任务、下载和退出；检查浏览器不存在 HTTP Cookie、CORS 错误或混合内容；外部端口扫描确认本机 18888 不可直接访问。
- 验收标准：本机、局域网、公网三种访问路径的行为符合设计。

## 八、文档和发布流程

### DOC-01 更新部署文档 — 8 分

- 状态：`[-]`
- 单机版文档重点：Windows 环境准备、随机管理员密码、花生壳隧道、Host 白名单、HTTPS Cookie、Windows 防火墙、启动/停止、备份/恢复和日志位置。
- 文档需要同时说明 SQLite/ORM 基础阶段和 PostgreSQL 迁移阶段；Redis、任务队列和多 worker 仍暂不纳入。
- 验收标准：新机器可以按照文档完成部署、创建管理员、配置 GPU/TTS、启动服务和恢复备份。

### DOC-02 建立版本升级和回滚流程 — 8 分

- 状态：`[-]`
- 当前状态：Alembic 已有 0001~0004 版本化迁移链，数据库结构变更具备升级/回滚基础；独立的升级/回滚操作 runbook 尚未成文。
- 改造方向：发布前备份数据库、配置、模型路径和输出目录；记录 Python/Node/CUDA/FFmpeg/数据库版本；数据库迁移前执行备份和检查；保留上一版代码和回滚命令。
- 验收标准：升级失败时可以恢复到上一版本，不会因为代码回滚而破坏数据库结构。

## 推荐实施批次

### 批次 1：ORM 基础层，SQLite 保持不变（已完成）

- 核对真实 SQLite schema，处理 `bgm_tracks.loudness` 等字段漂移。
- 建立 SQLAlchemy 2.x Engine、Session、Models 和 Store 适配层；首批 `settings_store` 业务读写已切换到 ORM。
- 建立 Alembic baseline，并验证现有 SQLite 数据和全部业务测试。
- 保持公共音色、模板文件和任务产物 JSON 的现有存储方式。

### 批次 2：PostgreSQL 迁移验证（已完成）

- 新增 `DATABASE_URL` 和 PostgreSQL 环境配置。
- 编写 SQLite → PostgreSQL 数据导入、行数核对、文件资源核对和回滚脚本。
- 先在测试/备用环境运行 PostgreSQL，再切换生产配置。
- 单进程、小连接池运行，观察锁等待、事务耗时和任务行为。

### 批次 3：公网运行与单机运营

- 确认任务/输出/配置/BGM/模板的用户边界（音色库保持公共读写，不做收紧）。
- 完成花生壳域名、Host 白名单、HTTPS、Cookie、CSRF、CORS 和 Windows 防火墙验证。
- 完成每用户并发、Qwen-TTS/FFmpeg/RunningHub 全局并发、上传限制和磁盘低水位保护（已完成：孤儿扫描/过期清理/低磁盘拒绝见 RESOURCE-02、RESOURCE-04）。
- 完成数据库、配置、公共音色目录和输出目录备份，以及恢复演练。
- 完成真实公网域名登录、上传、生成、下载和退出冒烟测试。

### 批次 4：按需求决定的扩展

- Redis、独立任务队列、可恢复 worker、多 worker。
- `task_artifacts`、`user_usage_daily`、复杂审计表和私有音色。
- pgvector、模板数据库化和更细的用量/审计分析。

## 当前已有基础

- Session Token 在数据库中保存哈希，而不是明文。
- 密码使用随机 Salt 和固定成本的 PBKDF2 计算，并使用常量时间比较。
- 已有普通用户/管理员的路由依赖。
- 任务、产物和部分输出路径已经有用户归属和路径边界检查。
- `extra_info` 对常见敏感字段有过滤。
- BGM、模板和任务相关代码已有部分用户隔离测试。
- 前端已经统一通过 `apiFetch` 请求后端，适合集中加入 CSRF、请求 ID 和错误处理。

## 暂不处理或不作为首要目标

- 不为了认证问题立刻引入完整的企业 IAM/SSO 平台。
- 不把 ORM/ PostgreSQL 迁移和 Redis、任务队列、多 worker、pgvector 绑定成一次大改造。
- 不把公共音色库强行改成按用户隔离；所有登录用户公共读写是当前确定的模型。
- 不把视频、音频和图片二进制直接存入数据库。
- 不在没有备份、迁移核对和恢复演练的情况下切换生产数据库。
- 不借数据库迁移顺便改变 API 业务语义或重构所有文件型资源。

## 本轮已完成（不改六张业务表结构和业务数据）

- 已完成任务并发限制：`tasks.max_running_tasks_per_user` 控制单用户占用，`max_active_jobs + max_queued_jobs` 自动形成全局接纳上限；创建任务前校验未完成任务数，超额返回 429；音色库确认保持所有登录用户公共读写，取消管理员写限制。

- 已完成认证基线：关闭默认公开注册、取消固定管理员密码、首用户不自动成为管理员、登录/注册限流、密码长度上限、Session 清理与数量上限。
- 已完成浏览器会话防护：动态判断本机 HTTP 与穿透 HTTPS 的 `Secure` Cookie；生产示例启用双提交 CSRF，前端自动发送 `X-CSRF-Token`。
- 已完成公网入口基线：默认监听回环地址、生产关闭 reload、Host 校验、CORS 白名单、安全响应头、请求体上限。
- 已完成上传资源基线：音频/图片/视频/JSON 统一大小、扩展名、MIME 和原子临时文件校验。
- 已完成 LLM 出站地址基线：默认拒绝回环、私网、链路本地、保留地址和本机主机名；可通过环境变量显式放行内部 LLM。
- 已补充认证、CSRF、上传限制和 LLM 地址校验测试；当前后端全量测试为 161 个通过，前端生产构建通过。

> 本轮没有修改六张 SQLite 业务表结构、任务模型或业务数据内容；新增的 `alembic_version` 仅用于记录迁移版本。已建立 SQLAlchemy ORM 基础层和 Alembic baseline，`settings_store` 的用户读取、配置、字幕替换和 BGM CRUD 已切换到 ORM；`auth_store` 和 `task_store` 暂未切换。音色库按公共资源设计，未做用户归属隔离；PostgreSQL、剩余 Store 迁移和任务队列等仍按后续阶段处理。

## 本次重新审视结论

当前项目不是“准备承载大量租户的 SaaS”，而是“单台 Windows 主机上的小规模共享服务”。因此，下一阶段的核心不是把所有 Java 后端常见组件补齐，而是把有限资源和公网暴露风险控制住。

当前明确要做：

- 先在 SQLite 上引入 SQLAlchemy 2.x 和 Alembic，保持业务行为不变。
- ORM 层稳定后迁移 PostgreSQL，保留 SQLite 回滚和开发能力一段时间。
- 公共音色库保持所有登录用户公共读写，不做强制用户隔离。
- 以进程内信号量、现有任务表、备份和 Windows 进程托管保证单机可运营。

当前仍暂缓：

- Redis、独立任务队列、多 worker、每日用量统计表。
- `generation_tasks.artifacts_json` 拆成独立产物表。
- 私有音色、复杂审计表、模板数据库化和 pgvector。

建议的升级触发条件只用于后续基础设施：出现多 worker/多主机需求、任务排队明显、备份恢复无法满足要求，或稳定并发长期超过约 10～20 时，再评估 Redis、队列和更强的任务模型；PostgreSQL/ORM 则按本路线推进，不再等待这些触发条件。
