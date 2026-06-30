# Video Factory

Video Factory 是一个本地运行的 AI 视频生产工作台。当前已经接入的功能是“数字人口播视频”：前端负责素材、文案、音色和语言选择；后端负责本地 TTS、RunningHub 工作流调用和生成结果管理。

## 项目结构

```text
web-app/
  main.py                 FastAPI 后端入口，也负责生产模式下托管前端静态文件
  config.example.yaml     本地配置模板
  config.yaml             本地私有配置，已被 .gitignore 忽略
  requirements.txt        Python 后端依赖
  start_dev.bat           Windows 开发模式一键启动脚本
  routers/                API 路由
  services/               RunningHub 和本地 TTS 集成
  frontend/               React + Vite 前端
```

## 部署前准备

需要在目标电脑上准备：

- Git
- Anaconda 或 Miniconda
- Node.js / npm
- NVIDIA 显卡驱动
- RunningHub API Key
- RunningHub 数字人工作流 ID
- Hugging Face 上的 Qwen3-TTS 模型文件

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

## 安装前端依赖

```powershell
cd D:\project\video-factory\web-app\frontend
npm install
```

## 下载 Hugging Face 模型

本项目支持两种 Qwen3-TTS 模式：

- `CustomVoice`：使用官方内置音色
- `Base`：使用参考音频 + 参考文本做 voice clone

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

下载 CustomVoice 模型：

```powershell
hf download Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice
```

下载 Base 模型：

```powershell
hf download Qwen/Qwen3-TTS-12Hz-1.7B-Base
```

如果希望下载到一个普通目录，而不是 Hugging Face cache，可以使用：

```powershell
hf download Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice --local-dir D:\models\Qwen3-TTS-12Hz-0.6B-CustomVoice
```

```powershell
hf download Qwen/Qwen3-TTS-12Hz-1.7B-Base --local-dir D:\models\Qwen3-TTS-12Hz-1.7B-Base
```

`config.yaml` 里的模型路径要分别填写：

```yaml
tts:
  customvoice_model_path: "D:/models/Qwen3-TTS-12Hz-0.6B-CustomVoice"
  base_model_path: "D:/models/Qwen3-TTS-12Hz-1.7B-Base"
```

或者填写 Hugging Face cache 里的 snapshot 路径：

```yaml
tts:
  customvoice_model_path: "D:/models/hf_home/hub/models--Qwen--Qwen3-TTS-12Hz-0.6B-CustomVoice/snapshots/<revision>"
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
runninghub:
  api_key: "你的 RunningHub API Key"
  concurrent_limit: 1
  instance_type: null

tts:
  customvoice_model_path: "D:/models/Qwen3-TTS-12Hz-0.6B-CustomVoice"
  base_model_path: "D:/models/Qwen3-TTS-12Hz-1.7B-Base"
  device: "cuda"
  default_speaker: "Uncle_Fu"
  default_language: "Chinese"

workflow:
  digital_human_id: "你的 RunningHub 数字人工作流 ID"

server:
  host: "0.0.0.0"
  port: 8001
  output_dir: "output"
```

配置说明：

- `runninghub.api_key`：RunningHub 的 API Key。也可以启动后在“设置”页面保存。
- `runninghub.instance_type`：RunningHub 实例类型；不确定就保留 `null`。
- `tts.customvoice_model_path`：CustomVoice 模型目录。
- `tts.base_model_path`：Base voice clone 模型目录。
- `tts.device`：有 NVIDIA GPU 时通常填 `cuda`；只用 CPU 时填 `cpu`，但生成会很慢。
- `tts.default_speaker`：CustomVoice 的默认音色。
- `tts.default_language`：默认语言。
- `workflow.digital_human_id`：RunningHub 上用于数字人口播视频的工作流 ID。
- `server.output_dir`：生成的音频、视频输出目录，相对路径会解析到 `web-app/output`。

Base 模式在页面里会让你上传：

- 参考音频 `ref_audio`
- 参考文本 `ref_text`

然后模型会根据参考音频克隆音色，再生成你输入的目标文案。

`web-app/config.yaml` 包含密钥，已经被 `.gitignore` 忽略，不要提交到 Git。

## 开发模式启动

开发模式会同时启动后端和前端：

```powershell
cd D:\project\video-factory\web-app
.\start_dev.bat
```

脚本会打开两个窗口：

- Backend: `http://127.0.0.1:8001`
- Frontend: `http://localhost:5173`

开发时访问：

```text
http://localhost:5173
```

前端开发服务会把 `/api` 和 `/output` 代理到后端。

## 生产模式部署

生产模式不需要单独启动 Vite 前端服务。先构建前端：

```powershell
cd D:\project\video-factory\web-app\frontend
npm run build
```

然后只启动 FastAPI：

```powershell
cd D:\project\video-factory\web-app
python -m uvicorn main:app --host 0.0.0.0 --port 8001
```

生产模式访问：

```text
http://目标电脑IP:8001
```

原因是 `main.py` 会在检测到 `web-app/frontend/dist` 存在时，自动把构建后的前端页面挂载到 FastAPI 根路径。也就是说生产部署只需要一个后端服务。

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
Invoke-RestMethod http://127.0.0.1:8001/api/health
```

检查音色接口：

```powershell
Invoke-RestMethod http://127.0.0.1:8001/api/speakers
```

检查语言接口：

```powershell
Invoke-RestMethod http://127.0.0.1:8001/api/tts/languages
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
