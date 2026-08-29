# Claude 设计基线（Design Source of Truth）

本目录是 **video-factory 前端的设计规范基线**，整体引进自 `example/Claude` 设计系统。

| 文件 | 作用 |
|---|---|
| `design-tokens.css` | **唯一 token 源**：原色阶（brand/text/bg/icon/border/success/error 50–900）、语义 token、字体（Newsreader/Poppins/Lora/Geist Mono）、圆角、间距、阴影、暗色备用块。由 `main.jsx` 全局引入，App.css 与 theme.js 的值都应来自这里。 |
| `css.json` | token 的机器可读版（与 design-tokens.css 同源），供工具链/自动同步使用。 |
| `spec/` | 组件规格文档（Button/Card/Input/Badge/ChatBubble/Navigation 的 JSON 定义 + HTML 预览 + ui_kits 组合参考）。**仅作查阅，不参与构建。** |

## 约定

1. **改主题先改这里**：调整品牌色/字体/圆角，改 `design-tokens.css`，然后同步 `src/theme.js`（MUI 消费侧）；App.css 里的旧名变量（`--accent` 等）是映射垫片，会自动跟随。
2. 四字体分工：Newsreader=大标题 · Poppins=UI chrome 短文字 · Lora=被阅读的内容（输入框值/段落） · Geist Mono=技术标注。速查页见 `docs/claude-font-preview.html`。
3. 暗色 token 已随文件引进（`.dark` 块），当前未激活；激活时在 `theme.js` 配 colorSchemes 即可。
4. 来源：`example/Claude`（Anthropic 风格重构版设计系统，仅作内部设计用途）。
