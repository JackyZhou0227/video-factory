# Frontend Guidelines

## Component Library

All frontend UI must use MUI components from `@mui/material`. Prefer `Box`, `Stack`, `Grid`, `Typography`, `Paper`, `Button`, `IconButton`, `TextField`, `Select`, `Dialog`, and related MUI primitives for layout, text, controls, and surfaces. Do not add raw `<button>`, `<input>`, or `<select>` when an MUI equivalent exists. Semantic elements such as `main`, `nav`, and `section` remain acceptable for document structure.

Use icons from the existing MUI icon library where available. Keep component logic in `src/components/`, shared browser helpers in `src/lib/`, and application-wide theme behavior in `src/theme.js`.

## Design System

The repository-local design guide is `../../docs/design-system/claude-theme/`. For every frontend UI or visual-design task, first read `../../docs/design-system/claude-theme/SKILL.md`, then read only the component definitions, previews, or UIKit reference relevant to the task. This workflow must work without an installed global Skill.

The application consumes the system through `src/theme.js` and `src/styles/claude/design-tokens.css`; do not import files from `docs/` into runtime code. Reuse the documented tokens, typography roles, spacing, radii, shadows, and restrained terra-cotta accent. Do not introduce arbitrary colors, font families, or duplicated token values. When intentionally changing tokens or component specifications, update both the complete reference under `docs/design-system/claude-theme/` and its runtime copy under `src/styles/claude/`.

Follow the system's warm, calm, editorial hierarchy: serif display emphasis, readable body text, compact sans-serif UI, open spacing, tonal separation, and restrained borders and shadows. Never depend on a user-specific global Skill path.

## Verification

Run `npm run build` from `web-app/frontend/` after frontend changes. The build hook packages project skills automatically. Keep generated archives under `public/skills/` and `dist/skills/` out of commits.
