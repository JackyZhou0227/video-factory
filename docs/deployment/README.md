# 部署

按操作系统分开写。命令都在 `web-app` 目录下执行。

| 系统 | 文档 | 状态 |
| --- | --- | --- |
| Windows | [Windows 部署](windows.md) | 当前可用：前台启动，以及用 WinSW 注册成服务 |
| Linux | 尚未编写 | 计划用同一套应用目录和 `config.yaml`，进程托管方式另写 |

应用配置始终是 `web-app/config.yaml`。生产进程读取这份文件，不读取当前工作目录下的其他配置。
