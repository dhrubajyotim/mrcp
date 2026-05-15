# MRCP Cardiology MCQ Portal

A self-hosted medical MCQ web application built from a PassMedicine Cardiology PDF (572 questions). Supports timed quiz mode and instant-feedback practice mode with JWT authentication.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      Browser (Client)                   │
│  index.html ─► dashboard.html ─┬─► quiz.html           │
│                                ├─► practice.html        │
│                                ├─► results.html         │
│                                └─► history.html         │
│  Shared: style.css + app.js (auth helpers)              │
└────────────────────┬────────────────────────────────────┘
                     │  HTTP / JSON (JWT in header)
                     ▼
┌─────────────────────────────────────────────────────────┐
│              FastAPI Server  (main.py)                   │
│                                                         │
│  POST /auth/register       Register new user            │
│  POST /auth/login          Login → JWT token            │
│                                                         │
│  GET  /topics              List all topics               │
│  POST /quiz/start          Start quiz/practice session  │
│  POST /quiz/submit         Submit full quiz & end       │
│  POST /quiz/submit-single  Submit one answer (practice) │
│  GET  /quiz/history        Past session results         │
│  GET  /quiz/history/{id}   Detailed session review      │
│                                                         │
│  auth.py ── JWT creation & verification (python-jose)   │
│  models.py ── SQLAlchemy ORM models                     │
│  database.py ── DB engine, session, migrations          │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│               SQLite Database  (mcq.db)                 │
│                                                         │
│  users          ── id, email, hashed_password            │
│  questions      ── id, number, topic, scenario, stem,   │
│                    opt_1..opt_5, correct_opt,            │
│                    explanation, tagline, images          │
│  quiz_sessions  ── id, user_id, topic, score, started,  │
│                    ended, time_limit                     │
│  quiz_answers   ── id, session_id, question_id,         │
│                    selected_opt, is_correct              │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│           static/images/q{n}/  (extracted PNGs)         │
│           394 of 560 questions have explanation images   │
└─────────────────────────────────────────────────────────┘
```

### PDF Parser (offline tool)

```
parse_pdf.py ── PyMuPDF-based parser
  ├── Extracts questions, options, correct answers (green-border detection)
  ├── Extracts explanation images (≥200×80px) into static/images/q{n}/
  ├── Strips noise (dates, page headers) via _STRIP_RE regex
  └── Modes: full parse  |  --images-only (re-extract images only)
```

---

## Project Structure

```
mrcp/
├── main.py              # FastAPI app – all API endpoints
├── auth.py              # JWT token creation & verification
├── models.py            # SQLAlchemy models (User, Question, QuizSession, QuizAnswer)
├── database.py          # DB engine, SessionLocal, run_migrations()
├── parse_pdf.py         # PDF → database parser (run once)
├── requirements.txt     # Python dependencies
├── .env                 # Secret key & DB URL (not committed)
├── .env.example         # Template for .env
├── .gitignore           # Excludes .env, *.db, *.pdf, __pycache__
├── mcq.db               # SQLite database (560 questions)
├── static/
│   ├── index.html       # Login / Register page
│   ├── dashboard.html   # Topic picker + Quiz/Practice mode toggle
│   ├── quiz.html        # Timed quiz mode
│   ├── practice.html    # Practice mode (instant answer reveal)
│   ├── results.html     # Post-quiz score & review
│   ├── history.html     # Past session history
│   ├── style.css        # All styles
│   ├── app.js           # Auth helpers (token storage, fetch wrapper)
│   └── images/          # Extracted explanation images (q1/, q2/, ...)
├── show_db.py           # Admin: view DB summary
└── reset_password.py    # Admin: reset user password
```

---

## Quick Start

### Prerequisites

- Python 3.10+
- ngrok (for public access) — https://ngrok.com/download

### 1. Install dependencies

```powershell
cd C:\Users\mdhru\OneDrive\Desktop\mrcp
pip install -r requirements.txt
```

### 2. Set up environment

```powershell
# Copy and edit .env (already done if you have a .env file)
copy .env.example .env
# Edit .env and set a strong SECRET_KEY
```

### 3. Parse PDF (first time only)

```powershell
# Full parse (questions + images)
python parse_pdf.py "1.Cardiology MRCP 1 Passmedicine 2024.pdf"

# Re-extract images only
python parse_pdf.py "1.Cardiology MRCP 1 Passmedicine 2024.pdf" --images-only
```

### 4. Launch the web app

```powershell
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

App is now running at **http://localhost:8000**

---

## Free Hosted Deployment

Recommended free-tier split:

```
Firebase Hosting  -> static frontend and explanation images
Render Web Service -> FastAPI backend
Turso              -> hosted SQLite/libSQL database
```

Included deployment files:

- `firebase.json` for Firebase Hosting
- `.firebaserc.example` as a Firebase project template
- `render.yaml` for a Render free web service
- `static/config.js` for the frontend API URL
- `import_to_turso.py` to copy `mcq.db` questions into Turso

### 1. Create Turso database

On Windows, Turso recommends installing the CLI through WSL. Open PowerShell:

```powershell
wsl
```

Inside WSL:

```bash
curl -sSfL https://get.tur.so/install.sh | bash
exec $SHELL
turso
turso auth login
turso db create mrcp
turso db show --url mrcp
turso db tokens create mrcp
```

Copy the URL and token from the last two commands. Back in PowerShell, set them
for the import command:

```powershell
cd C:\Users\mdhru\OneDrive\Desktop\mrcp
$env:TURSO_DATABASE_URL="libsql://your-db-your-org.turso.io"
$env:TURSO_AUTH_TOKEN="your-token"
```

Install dependencies and import the local questions:

```powershell
pip install -r requirements.txt
python import_to_turso.py --replace
```

By default this imports only the question bank. To also copy local users and
quiz history, use:

```powershell
python import_to_turso.py --replace --include-users
```

### 2. Deploy backend to Render

Render deploys from a Git repo. First push this folder to GitHub. Replace
`YOUR_GITHUB_USERNAME` and `mrcp` if your repo name is different:

```powershell
cd C:\Users\mdhru\OneDrive\Desktop\mrcp
git init
git add .
git commit -m "Prepare deployment"
git branch -M main
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/mrcp.git
git push -u origin main
```

Install Render CLI, log in, and validate `render.yaml`. On Windows, download
the Render CLI executable from the Render releases page and make sure `render`
is on your PATH. Then run:

```powershell
render login
render blueprints validate render.yaml
```

Create the Render web service from the CLI. Replace the placeholders first:

```powershell
$repoUrl="https://github.com/YOUR_GITHUB_USERNAME/mrcp"
$secretKey="replace-with-a-long-random-secret"
$tursoUrl="libsql://your-db-your-org.turso.io"
$tursoToken="your-turso-token"
$corsOrigins="https://your-firebase-project-id.web.app,https://your-firebase-project-id.firebaseapp.com"

render services create --confirm `
  --type web `
  --name mrcp-api `
  --runtime python `
  --repo $repoUrl `
  --branch main `
  --plan free `
  --build-command "pip install -r requirements.txt" `
  --start-command 'uvicorn main:app --host 0.0.0.0 --port $PORT' `
  --health-check-path /health `
  --env-var "SECRET_KEY=$secretKey" `
  --env-var "PYTHON_VERSION=3.11.11" `
  --env-var "TURSO_DATABASE_URL=$tursoUrl" `
  --env-var "TURSO_AUTH_TOKEN=$tursoToken" `
  --env-var "CORS_ORIGINS=$corsOrigins" `
  --env-var "MAX_REQUEST_BYTES=262144" `
  --env-var "AUTH_RATE_LIMIT_PER_MINUTE=8" `
  --env-var "API_RATE_LIMIT_PER_MINUTE=120"
```

Render will print or show your service URL, for example
`https://mrcp-api.onrender.com`. Save that URL for Firebase.

Dashboard fallback: create a new Render Web Service from the same GitHub repo
and use exactly these settings:

```text
Name: mrcp-api
Runtime: Python
Plan: Free
Build Command: pip install -r requirements.txt
Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT
Health Check Path: /health
Environment variables:
  SECRET_KEY=<long random string>
  PYTHON_VERSION=3.11.11
  TURSO_DATABASE_URL=libsql://your-db-your-org.turso.io
  TURSO_AUTH_TOKEN=<your Turso token>
  CORS_ORIGINS=https://your-firebase-project-id.web.app,https://your-firebase-project-id.firebaseapp.com
  MAX_REQUEST_BYTES=262144
  AUTH_RATE_LIMIT_PER_MINUTE=8
  API_RATE_LIMIT_PER_MINUTE=120
```

If you are using Render only, without Firebase, set:

```text
CORS_ORIGINS=*
```

### Basic abuse protection

The app includes lightweight in-process protection for the free Render setup:

```text
MAX_REQUEST_BYTES=262144
AUTH_RATE_LIMIT_PER_MINUTE=8
API_RATE_LIMIT_PER_MINUTE=120
```

This protects login/register routes and API routes from simple request floods.
It does not replace provider-level DDoS protection. For a public app with many
unknown users, put a custom domain behind Cloudflare and enable WAF/rate-limit
rules there before forwarding traffic to Render.

### 3. Deploy frontend to Firebase Hosting

Install Firebase CLI:

```powershell
cd C:\Users\mdhru\OneDrive\Desktop\mrcp
npm install -g firebase-tools
firebase login
```

Create or select your Firebase project. For a new project:

```powershell
firebase projects:create your-project-id
copy .firebaserc.example .firebaserc
```

Edit `.firebaserc` and replace `your-firebase-project-id` with your real
project ID.

Set the frontend API URL to your Render backend URL. Replace the URL:

```powershell
(Get-Content static\config.js) -replace 'window\.MRCP_API_BASE_URL = ".*";', 'window.MRCP_API_BASE_URL = "https://mrcp-api.onrender.com";' | Set-Content static\config.js -Encoding utf8
```

Deploy Firebase Hosting:

```powershell
firebase deploy --only hosting
```

After Firebase prints the hosting URL, update Render's `CORS_ORIGINS` in the
Render dashboard if the Firebase URL is different from the placeholder. Then
redeploy Render:

```powershell
render services
render deploys create mrcp-api --wait
```

### 5. Expose via ngrok (public access)

Open a **separate terminal**:

```powershell
ngrok http 8000
```

ngrok will display a public URL like:
```
Forwarding  https://xxxx-xxxx.ngrok-free.app -> http://localhost:8000
```

Share that URL with others to access the app.

### 6. Stop everything

- **uvicorn**: `Ctrl+C` in the server terminal
- **ngrok**: `Ctrl+C` in the ngrok terminal

---

## Admin Utilities

```powershell
# View database summary (users, questions, topics, sessions)
python show_db.py

# Reset a user's password
python reset_password.py user@email.com newpassword123
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + uvicorn |
| Database | SQLite + SQLAlchemy |
| Auth | JWT (python-jose) + bcrypt (passlib) |
| PDF Parsing | PyMuPDF (fitz) |
| Frontend | Vanilla HTML / CSS / JavaScript |
| Tunnel | ngrok |
