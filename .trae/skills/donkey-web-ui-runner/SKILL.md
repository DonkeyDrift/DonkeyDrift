---
name: "donkey-web-ui-runner"
description: "Starts the Donkey Car Web UI frontend and backend services. Invoke when the user asks to start, launch, or run the web interface."
---

# Donkey Car Web UI Runner

This skill automates the process of starting the Donkey Car Web UI services (both backend and frontend).

## Prerequisites
- **Python**: 3.11+ (Backend)
- **Node.js/npm**: Required for the React frontend

## Usage Guidelines

### 1. Start the Backend (FastAPI)
The backend is located in [backend](file:///c:/Dev/DDC/donkeycar/web_ui/backend).

**Installation:**
```bash
# From the project root (to install donkeycar in editable mode)
pip install -e . --ignore-requires-python
# Then from the backend directory
pip install -r requirements.txt
```

**Run:**
```bash
python main.py
```
- Host: `0.0.0.0`
- Port: `8000`

### 2. Start the Frontend (Vite/React)
The frontend is located in [frontend](file:///c:/Dev/DDC/donkeycar/web_ui/frontend).

**Installation:**
```bash
npm install
```

**Run:**
```bash
npm run dev
```
- Default URL: [http://localhost:5173/](http://localhost:5173/)

## Verification
- **Backend**: Check if `http://localhost:8000/` returns `{"message": "Donkey Car Web UI API is running"}`.
- **Frontend**: Open [http://localhost:5173/](http://localhost:5173/) and ensure the page loads without errors.

## Troubleshooting
- **ModuleNotFoundError**: Ensure `pip install -e .` was run from the root.
- **Port Conflict**: Check if ports `8000` or `5173` are already in use.
