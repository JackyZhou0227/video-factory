# 图片编辑

自定义 ComfyUI 上的 MOSS-Image 图片编辑。页面上用户上传一张原图，再填写提示词。负面提示词、采样参数和缩放都留在工作流原稿里。原稿把原图缩放到约 1M 像素（`megapixels` 为 1，边长对齐 16）。

## 当前使用的图

`json/` 里是 MOSS-Image 图片编辑（导出时的文件名是 `image_moss_image_edit`）。运行副本在 `web-app/workflows/selfhost/image_moss_image_edit.json`，由 `image-edit` 映射过去。需要 `moss_image_sft_int8_convrot.safetensors`、`moss_image_edit_lora_rank_64_bf16.safetensors`、`qwen3.5_9b_w4a8_gptq.safetensors` 和 `flux2-vae_small.safetensors`，缺模型时任务会报模型缺失。

原图先上传到 ComfyUI，再写到节点 `8`（LoadImage）的 `image`。提示词写到节点 `39` 的 `prompt`。

## 换一套图

目录名保持 `图片编辑`。用新图替换 `json/ui.json` 和 `json/api.json`，再把 API 格式复制到 `web-app/workflows/selfhost/`，并更新 `SELFHOST_WORKFLOW_MAPPING` 和字段上的节点绑定。
