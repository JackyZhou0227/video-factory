# Video Factory

Video Factory 是一个本地运行的 AI 视频生产工作台。当前包含数字人口播、独立语音合成、大字报视频和模板量产模块：前端负责素材、文案和生成参数，后端负责统一 LLM/TTS 调用、RunningHub 工作流和 FFmpeg 批量成片。

## 项目结构

```text
web-app/
  main.py                 FastAPI 后端入口，也负责生产模式下托管前端静态文件
  config.example.yaml     本地配置模板
  config.yaml             本地私有配置，已被 .gitignore 忽略
  requirements.txt        Python 后端依赖
  init_default_admin.bat  Windows 初始管理员账号脚本
  start_app.bat           Windows 一键启动脚本，同时提供前端页面和后端接口
  app/                    FastAPI 后端包
  data/                   本机运行数据与迁移备份，已被 .gitignore 忽略
  frontend/               React + Vite 前端
    skills/               可随前端打包下载的项目级 Skills 源码
```

## 项目 Skills

项目级 Skills 的唯一源码位于 `web-app/frontend/skills/`。这些 Skill 作为前端源码随 Git 管理，不会默认安装或复制到个人的 Agent Skills 目录。

当前包含：

- `web-app/frontend/skills/generate-smart-edit-copy/`：通过简短提问明确短视频需求，根据输入文案生成可直接复制的最终口播文案和有序素材关键词，并与“智能剪辑”页面配套使用。

每个 Skill 使用目录内的 `skill.json` 维护独立 SemVer 版本。修改 Skill 时直接编辑该目录并提升版本号，不需要移动文件或手动制作压缩包。`npm run dev` 和 `npm run build` 会先运行 `web-app/frontend/scripts/package_skills.py`，把最新版生成到 `public/skills/`；Vite 构建后会继续复制到 `dist/skills/`，供智能剪辑页面展示版本并下载。生成的 ZIP 属于构建产物，不提交 Git。

### Skill 版本展示约定

部分 Agent 的技能管理页面只展示 `SKILL.md` frontmatter 中的 `name` 和 `description`，不会读取项目自定义的 `skill.json`。为了让用户在安装后的技能卡片上直接看到版本，`description` 应以 `版本 vX.Y.Z｜` 开头；`skill.json` 继续作为前端下载文件名和项目版本管理的正式数据源。

发布新版本时必须同步修改两处版本号：

- `SKILL.md` 的 `description`，例如 `版本 v1.1.0｜……`；
- `skill.json` 的 `version`，例如 `"version": "1.1.0"`。

不要把版本号放进 `name`。名称应保持稳定并使用中文业务名称，避免版本升级后技能名称随之变化。Skill 内容和前端页面也应保持 Agent 品牌中立，以便同一个下载包用于不同的 Agent 产品。

下载的 ZIP 内保留完整 Skill 目录，并包含 `skill.json`。用户可以根据下载文件名或该文件中的版本号，与自己当前使用的 Skill 手动比较后决定是否更新；解压后可将完整目录放入所使用 Agent 的 Skills 目录。

## 部署前准备

需要在目标电脑上准备：

- Git
- Anaconda 或 Miniconda
- NVIDIA 显卡驱动（仅在本地模型使用 CUDA 时需要）
- RunningHub API Key
- Hugging Face 上的 Qwen3-TTS 模型文件（仅在启用本地音色克隆时需要）
- FFmpeg 与 FFprobe（模板量产和大字报视频使用）
- 可访问的 Edge-TTS 网络环境

客户运行时不需要 Node.js / npm；只有开发或重新构建前端时才需要。

建议使用 Python 3.10 或 3.11。Python 3.13 可能会遇到部分机器学习依赖没有预编译包的问题。

## 拉取代码

```powershell
cd D:\project
git clone git@github.com:JackyZhou0227/video-factory.git
cd video-factory
```

如果目标电脑没有配置 GitHub SSH key，也可以使用 HTTPS：

```powershell
git clone https://github.com/JackyZhou0227/video-factory.git
```

## 创建 Conda 环境

```powershell
conda create -n video-factory python=3.11 -y
conda activate video-factory
```

先安装适配目标显卡和 CUDA 驱动的 PyTorch。不要盲目使用固定命令，建议到 PyTorch 官方安装页选择 Windows、Pip、Python 和对应 CUDA 版本后复制命令：

```text
https://pytorch.org/get-started/locally/
```

安装完 PyTorch 后，再安装项目依赖：

```powershell
cd D:\project\video-factory\web-app
pip install -r requirements.txt
```

如果 `soundfile` 在 Windows 上报 `libsndfile` 相关错误，可以补装：

```powershell
conda install -c conda-forge libsndfile -y
```

## 构建前端

```powershell
cd D:\project\video-factory\web-app\frontend
npm install
npm run build
```

构建命令会同时打包项目 Skills，因此开发机还需要能够通过 `python` 命令运行当前后端 Python 环境。

## 下载 Hugging Face 模型

语音克隆使用 Qwen3-TTS Base 模型，通过参考音频和参考文本生成目标语音。在线预设音色由 Edge-TTS 提供，不需要下载额外模型。如果服务器不部署本地模型，可以跳过本节下载步骤，并保持 `tts.qwen3_tts_base.enabled: false`。

推荐先安装 Hugging Face Hub CLI：

```powershell
pip install -U "huggingface_hub[cli]"
```

建议把 Hugging Face 缓存放到容量较大的磁盘，例如：

```powershell
[Environment]::SetEnvironmentVariable("HF_HOME", "D:\models\hf_home", "User")
```

设置后重新打开 PowerShell，让环境变量生效。也可以只在当前终端临时设置：

```powershell
$env:HF_HOME = "D:\models\hf_home"
```

低配置机器优先下载 0.6B Base：

```powershell
hf download Qwen/Qwen3-TTS-12Hz-0.6B-Base
```

显存和内存充足时也可以使用 1.7B Base。代码按 Qwen3-TTS Base 架构加载，不限制具体参数规模：

```powershell
hf download Qwen/Qwen3-TTS-12Hz-1.7B-Base
```

如果希望把 0.6B Base 下载到普通目录，而不是 Hugging Face cache，可以使用：

```powershell
hf download Qwen/Qwen3-TTS-12Hz-0.6B-Base --local-dir D:/models/Qwen3-TTS-12Hz-0.6B-Base
```

`config.yaml` 里填写 Base 模型路径：

```yaml
tts:
  qwen3_tts_base:
    enabled: true
    model_path: "D:/models/Qwen3-TTS-12Hz-0.6B-Base"
    device: "cpu"
    concurrent_limit: 1
```

或者填写 Hugging Face cache 里的 snapshot 路径：

```yaml
tts:
  qwen3_tts_base:
    enabled: true
    model_path: "D:/models/hf_home/hub/models--Qwen--Qwen3-TTS-12Hz-0.6B-Base/snapshots/<revision>"
    device: "cpu"
    concurrent_limit: 1
```

## 配置本地 config.yaml

复制配置模板：

```powershell
cd D:\project\video-factory
Copy-Item web-app\config.example.yaml web-app\config.yaml
```

编辑 `web-app/config.yaml`：

服务器不部署本地模型时：

```yaml
tts:
  qwen3_tts_base:
    enabled: false
    model_path: ""
    device: "cpu"
    concurrent_limit: 1
  default_language: "Chinese"
  edge_default_voice: "zh-CN-XiaoxiaoNeural"
```

本机部署并启用 Qwen3-TTS Base 时：

```yaml
tts:
  qwen3_tts_base:
    enabled: true
    model_path: "D:/models/Qwen3-TTS-12Hz-0.6B-Base"
    device: "cpu"
    concurrent_limit: 1
  default_language: "Chinese"
  edge_default_voice: "zh-CN-XiaoxiaoNeural"

server:
  host: "0.0.0.0"
  port: 18888
  output_dir: "output"
```

配置说明：

- `tts.qwen3_tts_base.enabled`：是否在当前部署中启用本地 Qwen3-TTS Base。默认应为 `false`；关闭时后端不会检查模型路径、Python 依赖、PyTorch 或 CUDA，也不会尝试加载模型。
- `tts.qwen3_tts_base.model_path`：兼容的 Qwen3-TTS Base 模型目录，支持 0.6B Base 和 1.7B Base。仅在 `enabled: true` 时检查。
- `tts.qwen3_tts_base.device`：本地模型运行设备，支持 `cpu`、`cuda`、`cuda:0`、`cuda:1` 等。CPU 可以运行但通常较慢。
- `tts.qwen3_tts_base.concurrent_limit`：本地 Qwen3-TTS 的同时推理上限，默认建议 `1`；显存和负载充足时可小范围调到 `2`。
- `tts.default_language`：默认语言。
- `tts.edge_default_voice`：Edge-TTS 默认在线音色。
- `server.output_dir`：生成的音频、视频输出目录，相对路径会解析到 `web-app/output`。

本地 Qwen3-TTS Base 的状态判断分为两层：

1. `enabled: false` 时直接返回 `disabled`，跳过所有本地环境检测，适合不部署本地模型的云服务器。
2. `enabled: true` 时在后端启动阶段执行轻量验证：检查模型目录、`config.json`、Base 架构、权重文件、`qwen-tts`/`soundfile`/`torch` 依赖，以及配置的 CPU/CUDA 设备。

轻量验证不会加载完整模型权重。完整模型加载仍在第一次执行音色克隆时发生，避免启动服务或查询状态就占用大量内存或显存。验证结果会在当前后端进程中缓存，TTS 页面首次打开时直接读取缓存状态，不再触发本地模型检测。修改 `config.yaml`、模型文件、Python 依赖或设备环境后，需要重启后端以重新加载配置并执行检查。Edge-TTS 是云端预设音色，状态固定为静态可用；只有实际生成时才会触发网络调用。

CPU 模式使用 `float32` 加载；CUDA 模式使用 `bfloat16`。不支持 BF16 的旧显卡应配置为 `cpu`。如果状态原因包含 `libiomp5md.dll` 或 `OpenMP 运行库冲突`，说明当前 Python 环境同时加载了多份 Intel OpenMP DLL，需要修复 Conda/PyTorch 安装后再重启服务，不建议用 `KMP_DUPLICATE_LIB_OK` 绕过。

旧版扁平配置 `tts.base_model_path` 和 `tts.device` 不再使用。升级已有部署时，需要把它们迁移到 `tts.qwen3_tts_base.model_path` 和 `tts.qwen3_tts_base.device`，并显式设置 `tts.qwen3_tts_base.enabled: true`；未迁移时本地模型保持关闭。

音色克隆模式在页面里会让你上传：

- 参考音频 `ref_audio`
- 参考文本 `ref_text`

然后模型会根据参考音频克隆音色，再生成你输入的目标文案。

`web-app/config.yaml` 包含本机模型路径等私有配置，已经被 `.gitignore` 忽略，不要提交到 Git。

## 初始化管理员账号

首次部署时可以先创建一个本机管理员账号：

```powershell
cd D:\project\video-factory\web-app
.\init_default_admin.bat
```

默认账号：

```text
用户名：admin
密码：脚本会生成并打印一次性随机密码
```

`init_default_admin.bat` 只会在没有任何账号时创建初始管理员；用户表已有账号时，脚本不会覆盖已有数据。

如果需要自定义用户名或密码，可以直接调用底层脚本：

```powershell
python scripts\init_admin.py --username admin --display-name admin
```

如果不传 `--password`，底层脚本会自动生成一个随机密码并打印出来。

## 本机设置

登录后在页面“设置”里配置当前用户的 RunningHub API Key、并发限制和机器规格，以及 OpenAI 兼容 LLM 的 Base URL、API Key 和模型名称。

这些设置按用户保存在配置的 PostgreSQL 数据库。数字人 RunningHub 工作流 ID 是系统固定值，不在页面或数据库里让客户配置。

## 任务中心与产物

每次用户发起的生成请求对应一条 `generation_tasks` 任务记录，不按单个文件拆任务。任务中心默认只显示当前登录用户的任务，支持按任务类型、生成类型、状态和创建日期筛选，并提供产物预览、单文件下载和任务 ZIP 下载；不提供删除按钮。

任务类型固定为：

- `digital_human`：数字人视频，`generation_type=video`，RunningHub 接收成功即标记为 `completed`。
- `voice_generation`：语音生成，`generation_type=voice`；语音调速结果追加到原任务，不创建新任务。
- `poster_video`：大字报批量图片或视频，按一次批量请求记录 `requested_count`。
- `template_production`：模板量产视频；脚本生成和改写属于内部步骤，不单独建任务。

表中保存 `requested_count`、`success_count`、`failed_count`、状态、进度、创建人快照和 UTC ISO-8601 时间。供应商或业务特有信息统一放在 `extra_info_json`，例如数字人的 `runninghub_task_id`、工作流 ID 和外部链接；API Key 等敏感信息不会写入该字段。产物清单放在 `artifacts_json`，服务端路径只保存在后端，接口只返回产物 ID 和接口 URL。

任务文件使用日期优先的目录格式：

```text
web-app/output/tasks/YYYY/MM/DD/{task_type}/{task_id}/
```

日期按任务创建时间的 UTC 日期生成。例如：

```text
web-app/output/tasks/2026/08/07/voice_generation/3c8.../
web-app/output/tasks/2026/08/07/digital_human/71a.../
```

这样可以在不查数据库的情况下按日期手动清理早期文件。当前不实现定时删除、删除接口或历史任务回填；如果目录被手动删除，任务记录仍保留，详情会将相应产物标记为 `missing`，下载接口返回 `404`。

主要接口均要求登录会话：

- `GET /api/tasks`：分页查询当前用户任务。
- `GET /api/tasks/{task_id}`：查询任务详情和安全产物清单。
- `GET /api/tasks/{task_id}/artifacts/{artifact_id}/preview`：预览音频、图片或视频。
- `GET /api/tasks/{task_id}/artifacts/{artifact_id}/download`：下载单个产物。
- `GET /api/tasks/{task_id}/download`：优先下载任务 ZIP；只有一个产物时下载该产物。

接口始终根据当前用户校验任务归属，并对服务端路径执行目录边界检查。旧 `/output/*` 兼容接口也要求登录；背景音乐改用 `/api/template-production/bgm/{bgm_id}/audio`，音色参考音频继续使用音色接口。

## 模板 JSON

模板量产使用 Pydantic 校验的版本化 JSON 定义。模板只描述内容字段、素材槽、文案提示词和服务端流水线绑定，不包含某次任务填写的内容、上传文件、生成文案或任务状态。页面支持导入模板 JSON，也可以把当前模板直接导出。

内置模板位于 `web-app/app/templates/builtin/` 且不可覆盖；用户导入的模板按账号隔离保存在 `web-app/data/templates/users/`。导入文件最大为 128 KiB，当前只允许绑定 `generic_concat_v1` 或 `zhongyi_visit_v1`，不会执行模板中提供的 Python 表达式或任意函数。

模板接口：

- `GET /api/template-production/templates`：列出当前用户可用的内置模板和个人模板。
- `GET /api/template-production/templates/{template_id}`：读取模板详情。
- `POST /api/template-production/templates/import`：以 multipart 字段 `file` 导入模板 JSON。
- `GET /api/template-production/templates/{template_id}/export`：导出纯模板定义 JSON。

## 启动应用

完整启动（推荐）：创建或准备 `.venv`、激活虚拟环境、安装 Python 依赖，然后构建前端并启动服务：

```powershell
cd D:\project\video-factory\web-app
.\start.bat
```

如果当前命令行已经激活了正确的 Python 虚拟环境，也可以直接启动。`start_app.bat` 不会创建或激活虚拟环境，但会检查并安装前端依赖、执行 `npm run build`，再启动 FastAPI：

```powershell
cd D:\project\video-factory\web-app
.\start_app.bat
```

访问：

```text
http://127.0.0.1:18888
```

FastAPI 会在检测到 `web-app/frontend/dist` 存在时，自动把构建后的前端页面挂载到根路径，同时提供 `/api` 后端接口。

## 更新代码

目标电脑后续更新代码：

```powershell
cd D:\project\video-factory
git pull
```

如果只修改了前端代码，可以直接重新运行 `start_app.bat`，脚本会自动重新构建；也可以手动构建：

```powershell
cd web-app\frontend
npm install
npm run build
```

如果 Python 依赖有更新：

```powershell
cd D:\project\video-factory\web-app
pip install -r requirements.txt
```

## 常见检查

检查后端是否正常：

```powershell
Invoke-RestMethod http://127.0.0.1:18888/api/health
```

TTS Studio 接口需要登录会话。PowerShell 中可以先登录并保留 Cookie：

```powershell
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-RestMethod `
  -Uri http://127.0.0.1:18888/api/auth/login `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"username":"admin","password":"your-password"}' `
  -WebSession $session
```

检查 Edge-TTS 音色接口：

```powershell
Invoke-RestMethod http://127.0.0.1:18888/api/tts-studio/edge-tts/voices -WebSession $session
```

检查所有 TTS provider 状态：

```powershell
Invoke-RestMethod http://127.0.0.1:18888/api/tts-studio/providers -WebSession $session
```

Provider 状态含义：

- `edge_tts` 固定返回 `available`，`validation: static`，不会在状态接口中探测网络。
- `qwen3_tts_base` 返回 `disabled`：配置中主动关闭，未进行任何本地检测。
- `qwen3_tts_base` 返回 `unavailable`：已启用，但模型目录、模型文件、依赖或设备检查失败；`reason` 会给出原因。
- `qwen3_tts_base` 返回 `available`：启动期轻量检查通过，可以进入首次生成时的完整模型加载。

检查语言接口：

```powershell
Invoke-RestMethod http://127.0.0.1:18888/api/tts-studio/languages -WebSession $session
```

检查 PyTorch 是否能看到 NVIDIA GPU：

```powershell
python -c "import torch; print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
```

如果 `torch.cuda.is_available()` 是 `False`，通常需要检查：

- NVIDIA 驱动是否正确安装
- PyTorch 是否安装了 CUDA 版本
- 当前 Conda 环境是否就是运行服务的环境

## 官方文档

- Hugging Face CLI: https://huggingface.co/docs/huggingface_hub/en/guides/cli
- Hugging Face 环境变量: https://huggingface.co/docs/huggingface_hub/en/package_reference/environment_variables
- Hugging Face 下载说明: https://huggingface.co/docs/huggingface_hub/en/guides/download
- PyTorch 安装选择器: https://pytorch.org/get-started/locally/

## 预设音色库

音色克隆模式支持复用本地共享音色档案：

- 切到 `音色克隆 / Qwen3-TTS Base · 本地`
- 从共享克隆音色库选择已有声音档案
- 新增音色时上传参考音频和参考文本，保存后即可复用

预设数据默认保存在 `web-app/data/voice_profiles/`。
