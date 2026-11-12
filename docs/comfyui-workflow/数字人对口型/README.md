# 数字人对口型

RunningHub 上的对口型。用户上传人物形象图片和对口型音频，音频可以先在 TTS Studio 里生成。

运行时不用这里的 JSON 提交任务，只用 `web-app/workflows/runninghub/digital-human-lipsync.json` 里的 `workflow_id`。`json/api.json` 用来查证参数名：图片是 `$videoimage.image`，音频是 `$audio.audio`。

## 换一套图

目录名保持 `数字人对口型`。若仍走 RunningHub，替换 `json/` 里的原稿，并更新 runninghub 目录里的 `workflow_id`。若改成自定义 ComfyUI，再按 [上级说明](../README.md) 把 `api.json` 登记到 selfhost 映射。
