# Video Factory

Local web app for AI-assisted video production workflows.

## Structure

```text
web-app/
  main.py                 FastAPI backend entry
  config.example.yaml     Example config for local setup
  routers/                API routes
  services/               RunningHub and local TTS integrations
  frontend/               React/Vite frontend
```

## Setup

1. Copy the example config:

```powershell
Copy-Item web-app\config.example.yaml web-app\config.yaml
```

2. Fill in `web-app/config.yaml`:

- `runninghub.api_key`
- `workflow.digital_human_id`
- `tts.model_path`
- `tts.device`

3. Install backend dependencies:

```powershell
cd web-app
pip install -r requirements.txt
```

4. Install frontend dependencies:

```powershell
cd web-app\frontend
npm install
```

5. Start development server:

```powershell
cd web-app
.\start_dev.bat
```
