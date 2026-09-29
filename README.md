# Video Factory

Video Factory 是一个本地运行的 AI 视频生产工作台。当前包含数字人口播、独立语音合成、大字报视频和模板量产模块：前端负责素材、文案和生成参数，后端负责统一 LLM/TTS 调用、RunningHub 工作流和 FFmpeg 批量成片。

## 文档导航

README 只用于项目介绍和模块入口；每个模块的技术说明拆分在 `docs/modules/`。

| 目标 | 文档 |
| --- | --- |
| 数字人口播 | [数字人模块](docs/modules/digital-human.md) |
| 语音合成与音色克隆 | [TTS Studio 模块](docs/modules/tts-studio.md) |
| 大字报视频 | [大字报模块](docs/modules/poster-video.md) |
| 模板量产 | [模板量产模块](docs/modules/template-production.md) |
| 智能剪辑 | [智能剪辑模块](docs/modules/smart-editing.md) |
| 任务中心与产物 | [任务中心模块](docs/modules/task-center.md) |
| 项目 Skills | [Skills 模块](docs/modules/skills.md) |
| 所有文档入口 | [文档索引](docs/README.md) |

## 项目结构

```text
web-app/
  main.py                 FastAPI 后端入口，也负责生产模式下托管前端静态文件
  config.example.yaml     本地配置模板
  config.yaml             本地私有配置，已被 .gitignore 忽略
  requirements.txt        Python 后端依赖
  bootstrap.bat            创建/准备 .venv，安装 Python/前端依赖并构建前端
  start.bat                使用已有环境启动生产模式应用
  build.bat                只构建前端静态文件
  dev.bat                  启动后端热重载和 Vite 开发服务器
  init-admin.bat           初始化本机管理员账号
  app/                    FastAPI 后端包
  data/                   本机运行数据与迁移备份，已被 .gitignore 忽略
  frontend/               React + Vite 前端
    skills/               可随前端打包下载的项目级 Skills 源码
```

## 模块文档

从[文档索引](docs/README.md)进入各模块的技术说明。

发现文档错误或需要补充模块说明，请提交 Issue。


