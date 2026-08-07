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
  data/                   SQLite 和本机运行数据，已被 .gitignore 忽略
  frontend/               React + Vite 前端
```

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
密码：12345678
```

`init_default_admin.bat` 只会在没有任何账号时创建初始管理员；用户表已有账号时，脚本不会覆盖已有数据。

如果需要自定义用户名或密码，可以直接调用底层脚本：

```powershell
python scripts\init_admin.py --username admin --password 12345678 --display-name admin
```

如果不传 `--password`，底层脚本会自动生成一个随机密码并打印出来。

## 本机设置

登录后在页面“设置”里配置当前用户的 RunningHub API Key、并发限制和机器规格，以及 OpenAI 兼容 LLM 的 Base URL、API Key 和模型名称。

这些设置按用户保存在后端本机 SQLite：`web-app/data/video_factory.db`。数字人 RunningHub 工作流 ID 是系统固定值，不在页面或数据库里让客户配置。模板量产首版使用 Edge-TTS，生成任务状态只保存在当前后端进程中，服务重启后任务状态不会恢复。

## 模板 JSON

模板量产使用 Pydantic 校验的版本化 JSON 定义。模板只描述内容字段、素材槽、文案提示词和服务端流水线绑定，不包含某次任务填写的内容、上传文件、生成文案或任务状态。页面支持导入模板 JSON，也可以把当前模板直接导出。

内置模板位于 `web-app/app/templates/builtin/` 且不可覆盖；用户导入的模板按账号隔离保存在 `web-app/data/templates/users/`。导入文件最大为 128 KiB，当前只允许绑定 `generic_concat_v1` 或 `zhongyi_visit_v1`，不会执行模板中提供的 Python 表达式或任意函数。

模板接口：

- `GET /api/template-production/templates`：列出当前用户可用的内置模板和个人模板。
- `GET /api/template-production/templates/{template_id}`：读取模板详情。
- `POST /api/template-production/templates/import`：以 multipart 字段 `file` 导入模板 JSON。
- `GET /api/template-production/templates/{template_id}/export`：导出纯模板定义 JSON。

## 启动应用

```powershell
cd D:\project\video-factory\web-app
.\start_app.bat
```

访问：

```text
http://127.0.0.1:18888
```

`start_app.bat` 会启动 FastAPI。FastAPI 会在检测到 `web-app/frontend/dist` 存在时，自动把构建后的前端页面挂载到根路径，同时提供 `/api` 后端接口。也就是说用户只需要运行这一个脚本，就能同时访问前端和后端。

## 更新代码

目标电脑后续更新代码：

```powershell
cd D:\project\video-factory
git pull
```

如果前端代码有更新，重新构建：

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
