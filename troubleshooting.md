# Troubleshooting Guide — meldra.ai Local Environment

If you are starting up the environment and encounter browser compilation errors or database connection issues, use this guide to quickly resolve them.

---

## 1. Vite Browser Syntax / Cache Error
### The Symptom
The browser console displays an error similar to:
```
Uncaught SyntaxError: The requested module '/src/api.ts' does not provide an export named 'AWSConfig' (at main.ts:9:28)
```
And the interactive controls (tabs, prompts, buttons) do not respond.

### The Root Cause
Vite transpiles TypeScript files to ES Modules on the fly. The `AWSConfig` and `ChatMessage` interfaces are type-only definitions and generate no runtime code. If they are imported as values, the browser fails to locate their exports at runtime. 
We have split these into explicit `import type` statements in `main.ts`, but the browser may still serve a cached version of the older bundle.

### How to Fix
1. Make sure you have the latest code changes in `main.ts`.
2. Clear the browser cache and force-reload the page using **`Ctrl + F5`** (or `Cmd + Shift + R` on macOS).
3. If the issue persists, stop your Vite server in the terminal (`Ctrl + C`) and restart it with the clean-cache flag:
   ```powershell
   cd frontend/vite-project
   npm run dev -- --force
   ```

---

## 2. PostgreSQL / Apache AGE Password Authentication Error
### The Symptom
A red toast/popup in the bottom-right of the screen displays:
```
connection to server at "localhost" (::1), port 5432 failed: FATAL: password authentication failed for user "postgres"
```
The active database, nodes, and edges show warning triangles in the **AGE Graph** tab.

### The Root Cause
The FastAPI server is running on your host machine (`localhost:8000`) and tries to connect to PostgreSQL on port `5432` with the default password `password123`. 
If you have a **native/local PostgreSQL installation** running directly on Windows on port `5432`, the FastAPI server connects to your local service instead of the Docker container, leading to password mismatch or database name errors.

### How to Fix (Choose Option A or B)

#### Option A: Stop Windows PostgreSQL and use Docker (Recommended)
This frees up port `5432` so the Apache AGE database container can bind to it.
1. Open **PowerShell as Administrator** and stop the native service:
   ```powershell
   Stop-Service -Name postgresql*
   ```
   *(Alternatively, open Windows **Services** (`services.msc`), find the `postgresql-x64-...` service, right-click, and select **Stop**).*
2. Spin up the Apache AGE container:
   ```powershell
   docker compose up -d db
   ```

#### Option B: Run the Docker Container on a Custom Port (5433)
If you want to keep your Windows local PostgreSQL service running:
1. Open [docker-compose.yml](file:///c:/Users/sumit/Documents/icebergAgent/docker-compose.yml) and change the database port mapping to use `5433` on the host:
   ```yaml
   services:
     db:
       ...
       ports:
         - "5433:5432"
   ```
2. Create a `.env` file in the `backend/` directory to override the local database port setting for the FastAPI server:
   ```env
   GRAPH_DB_PORT=5433
   ```
3. Restart the database container:
   ```powershell
   docker compose down
   docker compose up -d db
   ```
4. Restart your FastAPI backend server:
   ```powershell
   cd backend
   uvicorn api.main:app --port 8000
   ```
