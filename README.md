# Video Factory

Video Factory 是一个本地运行的 AI 视频生产工作台。当前包含数字人口播、大字报视频和模板量产模块：前端负责素材、文案和生成参数，后端负责统一 LLM/TTS 调用、RunningHub 工作流和 FFmpeg 批量成片。

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
- NVIDIA 显卡驱动
- RunningHub API Key
- Hugging Face 上的 Qwen3-TTS 模型文件
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

语音克隆使用 Qwen3-TTS Base 模型，通过参考音频和参考文本生成目标语音。在线音色由 Edge-TTS 提供，不需要下载额外模型。

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

下载 Base 模型：

```powershell
hf download Qwen/Qwen3-TTS-12Hz-1.7B-Base
```

如果希望下载到一个普通目录，而不是 Hugging Face cache，可以使用：

```powershell
hf download Qwen/Qwen3-TTS-12Hz-1.7B-Base --local-dir D:\models\Qwen3-TTS-12Hz-1.7B-Base
```

`config.yaml` 里填写 Base 模型路径：

```yaml
tts:
  base_model_path: "D:/models/Qwen3-TTS-12Hz-1.7B-Base"
```

或者填写 Hugging Face cache 里的 snapshot 路径：

```yaml
tts:
  base_model_path: "D:/models/hf_home/hub/models--Qwen--Qwen3-TTS-12Hz-1.7B-Base/snapshots/<revision>"
```

## 配置本地 config.yaml

复制配置模板：

```powershell
cd D:\project\video-factory
Copy-Item web-app\config.example.yaml web-app\config.yaml
```

编辑 `web-app/config.yaml`：

```yaml
tts:
  base_model_path: "D:/models/Qwen3-TTS-12Hz-1.7B-Base"
  device: "cuda"
  default_language: "Chinese"
  edge_default_voice: "zh-CN-XiaoxiaoNeural"

server:
  host: "0.0.0.0"
  port: 18888
  output_dir: "output"
```

配置说明：

- `tts.base_model_path`：Base voice clone 模型目录。
- `tts.device`：有 NVIDIA GPU 时通常填 `cuda`；只用 CPU 时填 `cpu`，但生成会很慢。
- `tts.default_language`：默认语言。
- `tts.edge_default_voice`：Edge-TTS 默认在线音色。
- `server.output_dir`：生成的音频、视频输出目录，相对路径会解析到 `web-app/output`。

Base 模式在页面里会让你上传：

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

检查 Edge-TTS 音色接口：

```powershell
Invoke-RestMethod http://127.0.0.1:18888/api/tts-studio/edge-tts/voices
```

检查语言接口：

```powershell
Invoke-RestMethod http://127.0.0.1:18888/api/tts-studio/languages
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

Base 模式支持本地预设音色：

- 切到 `Base 语音克隆`
- 选 `预设音色` 就能直接复用已有声音档案
- 选 `新音色` 后，上传参考音频和参考文本，点击保存即可加入本地库

预设数据默认保存在 `web-app/data/voice_profiles/`。
