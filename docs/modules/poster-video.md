# 大字报模块

## 作用

批量上传图片或视频素材，统一转换为 9:16 竖屏，并叠加可编辑的大字报文字模板，输出图片或视频。

## 处理流程

1. 选择图片模式或视频模式。
2. 上传多份素材并填写文字内容。
3. 选择字体、颜色和布局参数。
4. 后端用 FFmpeg/图像处理流水线批量生成。
5. 任务中心提供逐项预览和下载。

## API 与实现

路由位于 `web-app/app/api/poster_video.py`：字体查询、批量生成和任务查询均以 `/api/poster-videos/` 开头。前端组件为 `web-app/frontend/src/components/PosterVideo.jsx`。

## 任务语义

一次批量请求对应一个 `poster_video` 任务，`requested_count` 表示请求数量，成功和失败数量记录在任务字段中。
