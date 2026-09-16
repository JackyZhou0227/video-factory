# Repository Guidelines

## Project Structure & Module Organization

The application lives under `web-app/`. The FastAPI backend is in `web-app/app/`, with routes in `app/api/`, configuration and security in `app/core/`, database code in `app/db/`, and business services in `app/services/`. Backend tests are under `web-app/tests/`. Migrations are in `web-app/alembic/`.

The React/Vite frontend is in `web-app/frontend/`: components are under `src/components/`, browser helpers under `src/lib/`, and static files under `public/`. Project skills are authored in `frontend/skills/`; generated archives in `public/skills/` and `dist/skills/` are build artifacts and should not be committed. Runtime configuration belongs in the ignored `web-app/config.yaml`, based on `config.example.yaml`.

## Build, Test, and Development Commands

Run from `web-app/` unless noted:

- `.\bootstrap.bat` creates `.venv`, installs Python and frontend dependencies, and builds the frontend.
- `.\dev.bat` starts FastAPI with reload and Vite at `http://127.0.0.1:5173`.
- `.\build.bat` runs the production frontend build.
- `.\start.bat` serves the built frontend and API in production mode on port `18888`.
- `python -m pytest` runs the backend suite. Tests use the PostgreSQL database `video_factory_test`; ensure PostgreSQL and `config.yaml` are configured first.
- `python -m alembic upgrade head` applies PostgreSQL migrations; use `python -m alembic current` to inspect the version.

From `web-app/frontend/`, `npm run dev`, `npm run build`, and `npm run preview` start Vite development, build production assets, and preview the build. Build hooks package project skills automatically.

## Coding Style & Naming Conventions

Use 4-space indentation for Python and 2-space indentation for JSX/JavaScript, with type hints and existing module boundaries. Use `snake_case` for Python files/functions and `PascalCase` for React components. Keep changes scoped to the owning directory. No repository-wide formatter or linter is configured; preserve surrounding style and run focused tests.

## Testing Guidelines

Add or update pytest tests alongside backend changes, using `test_*.py` files and descriptive `test_*` names. Cover authorization, validation, persistence, and external-service failures when relevant. Frontend changes must pass `npm run build`; add tests if a frontend test harness is introduced.

## Commit & Pull Request Guidelines

Use short Conventional Commit-style subjects, such as `feat:`, `fix:`, and `refactor:`. Keep commits focused. Pull requests should explain behavior changes, list verification commands, mention migrations or configuration changes, link related issues, and include screenshots for meaningful UI changes. Never commit secrets, `config.yaml`, runtime data, generated archives, or local output.

## Configuration & Data Safety

Do not place API keys, model paths, passwords, or production database URLs in tracked files. Back up production PostgreSQL before running migrations, and validate schema changes against `video_factory_test` first.
