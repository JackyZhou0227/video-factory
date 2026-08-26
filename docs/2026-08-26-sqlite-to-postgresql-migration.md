# SQLite 到 PostgreSQL 迁移说明（2026-08-26）

## 当前验证结论

本机 Windows PostgreSQL `17.11` 已完成测试迁移：

- 连接：`127.0.0.1:5432`
- 驱动：`psycopg==3.3.4`、`psycopg-binary==3.3.4`
- Alembic `upgrade head` 成功
- SQLite 六张业务表已成功导入 PostgreSQL
- 行数核对一致：`users=5`、`settings=12`、`sessions=15`、`subtitle_replacements=2`、`bgm_tracks=1`、`generation_tasks=14`
- `alembic check` 通过
- 设置 `DATABASE_URL` 后应用可以正常启动

迁移范围只包括数据库记录。BGM、任务产物、音色和上传文件仍然在文件系统中，迁移时必须同步保留对应目录。

## 正式环境前置条件

1. 安装 Python 依赖：

   ```powershell
   python -m pip install -r requirements.txt
   ```

2. 确认 PostgreSQL 服务正在运行，并准备空数据库。
3. 备份 SQLite 文件、`web-app/data/` 文件目录、配置文件和输出目录。
4. 停止应用，迁移期间禁止继续写入 SQLite。

## 正式迁移步骤

在 `web-app` 目录执行。密码不要写入仓库或命令历史，下面只使用占位符：

```powershell
$env:DATABASE_URL = "postgresql+psycopg://postgres:<PASSWORD>@127.0.0.1:5432/video_factory"

python -m alembic upgrade head

python scripts/migrate_sqlite_to_postgres.py `
  --sqlite data/video_factory.db `
  --postgres-url $env:DATABASE_URL

python -m alembic check
```

迁移脚本默认拒绝写入非空目标库；只有确认需要覆盖测试库时才使用 `--replace`。

## 迁移后核对

- 逐表核对行数、用户 ID、任务 ID 和外键关系。
- 使用 PostgreSQL 的 `DATABASE_URL` 启动应用。
- 验证登录、退出、配置读取/保存、任务创建/查询、BGM 列表/播放和历史产物下载。
- 检查任务输出目录和 BGM 目录仍与数据库中的相对路径一致。
- 观察启动日志、任务失败率和 PostgreSQL 连接数。

## 回滚边界

迁移完成并验证前保留 SQLite 备份和原文件目录。回滚时停止应用，恢复旧版本代码和 SQLite 配置；不要对已迁移的 PostgreSQL 数据库执行破坏性删除。

## 提交边界

应提交：ORM/Alembic 代码、`psycopg` 依赖、迁移脚本、测试修复和本说明文档。

不得提交：`web-app/config.yaml`、`web-app/data/video_factory.db`、数据库备份、测试库凭据、API Key、任务输出和 BGM 文件。

生产切换后，应用只要持续设置 `DATABASE_URL`，业务读写就全部走 PostgreSQL。SQLite 兼容代码暂时保留用于开发和回滚，生产环境不会调用它。
