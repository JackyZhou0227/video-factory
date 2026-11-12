# 文生图

自定义 ComfyUI 上的文生图。页面上用户填提示词，再选清晰度（480p、720p、1080p）和比例（1:1、4:3、3:4、3:2、2:3、16:9、9:16）。默认 720p、9:16。

负面提示词不展示。这套 Flux 图对负面提示词基本不起作用，节点里保持空字符串。

## 当前使用的图

`json/` 里现在是 Flux3 Klein 文生图（导出时的文件名是 `image_flux3_klein_t2i`）。运行副本在 `web-app/workflows/selfhost/image_flux3_klein_t2i.json`，由 `text-to-image` 映射过去。需要 Flux3 系列模型，缺模型时任务会报模型缺失。

清晰度和比例写到节点 `19`（ResolutionSelector，`multiple` 为 16）。提示词写到节点 `18:17`。边长会对齐到 16 的倍数，所以 1080p 的 16:9 是 1920×1072，不是 1920×1080。

## 换一套图

目录名保持 `文生图`。用新图替换 `json/ui.json` 和 `json/api.json`，再把 API 格式复制到 `web-app/workflows/selfhost/`，并更新 `SELFHOST_WORKFLOW_MAPPING` 和字段上的节点绑定。
