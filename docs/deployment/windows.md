# Windows 部署

在客户的 Windows 上运行 Video Factory。开发机可以前台启动；交给客户使用时注册成 Windows 服务，关窗口和注销不会把进程停掉。

以下命令都在 `web-app` 目录中执行。

## 准备

安装 Python 3、Node.js 和 PostgreSQL。PostgreSQL 需要先能在本机接受连接。

复制 `config.example.yaml` 为 `config.yaml`，至少填写 `database.url`。模型目录、输出目录写成绝对路径时，服务账户也要能读写这些路径。`server.output_dir` 若是相对路径 `output`，实际目录是 `web-app/output`。

首次准备环境：

```bat
scripts\bootstrap.bat
```

这会在仓库根目录创建 `.venv`，安装 Python 和前端依赖，并构建前端。用户表还是空的时，初始化管理员：

```bat
scripts\init-admin.bat
```

不传 `--password` 时会生成随机密码，并只在这次命令的输出里显示。

## 前台运行

```bat
scripts\start.bat
```

生产模式，关闭热重载，托管已经构建好的前端。缺 `frontend\dist` 时会先调用 `scripts\build.bat`。端口已被占用时直接退出。

开发模式用 `scripts\dev.bat`：API 带热重载，前端由 Vite 开在 `5173`。这不是客户机的运行方式。

## 注册为 Windows 服务

服务程序是 [WinSW 2.12 x64](https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe)。下载后保存为下面两个名字之一：

- `web-app\scripts\VideoFactory.exe`
- `web-app\scripts\WinSW-x64.exe`（安装脚本会复制成 `VideoFactory.exe`）

这个 exe 不要提交进仓库。它必须和 `scripts\VideoFactory.xml` 放在同一目录，并且主文件名相同。

用管理员身份打开命令行：

```bat
scripts\install-service.bat check
scripts\install-service.bat
```

`check` 不需要管理员，只确认虚拟环境、依赖、前端构建和 XML 都在。正式安装会注册名为 Video Factory 的服务，启动类型是自动（延迟启动），进程异常退出后会再拉起。

卸掉服务：

```bat
scripts\install-service.bat uninstall
```

日志写在 `web-app\scripts\logs`，按 10MB 滚动，保留 8 份。服务没有控制台窗口，启动失败看这里。

更新代码前先停止服务，需要时重新执行 `scripts\build.bat`，然后再启动。服务管理器里的名称是 Video Factory。

PostgreSQL 若装在本机，服务名因版本而异，所以 XML 里没有写死依赖，只做了延迟自动启动。数据库还没起来就启动应用时，把本机服务名写成 `VideoFactory.xml` 的 `<depend>`。

## 配置怎样生效

`app/core/config.py` 按源码位置读取 `web-app/config.yaml`。数据库、RunningHub、任务、登录、TTS 和输出目录都来自这份文件。页面里保存的 RunningHub 和 LLM 密钥在数据库中，随 `database.url` 一起用到。

`scripts\start.bat` 和 `VideoFactory.xml` 会设置这些环境变量，并盖过文件里的同名项：

| 环境变量 | 值 | 盖过的配置 |
| --- | --- | --- |
| `VIDEO_FACTORY_ENV` | `production` | `server.environment` |
| `VIDEO_FACTORY_RELOAD` | `0` | `server.reload` |
| `VIDEO_FACTORY_HOST` | `0.0.0.0` | `server.host` |
| `VIDEO_FACTORY_PORT` | `18888` | `server.port` |

`0.0.0.0` 是故意的：同一局域网里的其他机器可以用 `http://<本机IP>:18888` 直接打开。示例配置里的 `server.host` 也是这个值。若 `config.yaml` 写成别的地址，这两个启动方式仍以环境变量为准。改完 `config.yaml` 后要重启进程或服务才会重读。

服务以 LocalSystem 运行，不继承当前用户的 PATH。FFmpeg 若只装在用户 PATH 里，服务会找不到系统里的 `ffmpeg`；虚拟环境中的 `imageio-ffmpeg` 仍然可用。
