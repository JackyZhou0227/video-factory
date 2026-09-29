# Skills 模块

## 作用

项目级 Skills 随前端源码发布，用于把模板量产等复杂操作交给 Agent 辅助完成。源码唯一位置为 `web-app/frontend/skills/`。

当前 Skill：

- `generate-template-production-template`：生成可导入的模板量产 JSON，提供独立的格式校验和静音 MP4 预览脚本。

## 构建与版本

`npm run dev` 和 `npm run build` 自动执行打包脚本，输出到 `public/skills/` 和 `dist/skills/`。ZIP 是构建产物，不提交 Git。

每个 Skill 用目录内 `skill.json` 管理 SemVer；`SKILL.md` description 需同步写入 `版本 vX.Y.Z｜` 前缀。不要把版本号放进稳定的 Skill `name`。
