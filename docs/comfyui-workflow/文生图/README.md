# 文生图

自定义 ComfyUI 上的 MOSS-Image 文生图。页面上用户填提示词，再选清晰度（480p、720p、1080p）和比例（1:1、4:3、3:4、3:2、2:3、16:9、21:9、9:16）。默认 720p、9:16。

负面提示词、提示词增强、增强种子和 SLG 不展示。这四项留在工作流原稿里：负面提示词是 `nsfw, worst quality, bad anatomy, watermark, jpeg artifact`，提示词增强开着，增强种子是 0，SLG 关着。参考图只供给提示词增强，这张 API 图里没有接上，页面不提供。

## 当前使用的图

`json/` 里是 MOSS-Image 文生图（导出时的文件名是 `image_moss_image_t2i`）。运行副本在 `web-app/workflows/selfhost/image_moss_image_t2i.json`，由 `text-to-image` 映射过去。需要 `moss_image_sft_int8_convrot.safetensors`、`qwen3.5_9b_w4a8_gptq.safetensors` 和 `flux2-vae_small.safetensors`，缺模型时任务会报模型缺失。

清晰度和比例写到节点 `19`（ResolutionSelector，`multiple` 为 16）。三档按 16:9 标准帧的像素总量换算成 `megapixels`：480p 是 854×480，720p 是 1280×720，1080p 是 1920×1080。边长对齐到 16 后，16:9 实际是 848×480、1280×720、1920×1088。提示词写到节点 `18:17`。负面提示词、提示词增强、增强种子和 SLG 保持导出时的值，运行时不改。

## 换一套图

目录名保持 `文生图`。用新图替换 `json/ui.json` 和 `json/api.json`，再把 API 格式复制到 `web-app/workflows/selfhost/`，并更新 `SELFHOST_WORKFLOW_MAPPING` 和字段上的节点绑定。
