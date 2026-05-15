import json
import logging
import os
import random
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from auth import create_access_token, get_current_user, hash_password, verify_password
from database import engine, get_db, run_migrations
from models import Base, Question, QuizAnswer, QuizSession, User

load_dotenv()
Base.metadata.create_all(bind=engine)
run_migrations()
logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="MRCP MCQ Portal", docs_url="/api/docs", redoc_url=None)

MAX_REQUEST_BYTES = int(os.getenv("MAX_REQUEST_BYTES", str(256 * 1024)))
AUTH_RATE_LIMIT_PER_MINUTE = int(os.getenv("AUTH_RATE_LIMIT_PER_MINUTE", "8"))
API_RATE_LIMIT_PER_MINUTE = int(os.getenv("API_RATE_LIMIT_PER_MINUTE", "120"))
_rate_buckets = defaultdict(deque)

cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "*").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials="*" not in cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limit_key(request: Request) -> tuple[str, str]:
    group = "auth" if request.url.path.startswith("/auth/") else "api"
    return group, _client_ip(request)


def _rate_limit_for_path(path: str) -> int | None:
    if path.startswith("/static/") or path in {"/", "/health"}:
        return None
    if path.startswith("/auth/"):
        return AUTH_RATE_LIMIT_PER_MINUTE
    return API_RATE_LIMIT_PER_MINUTE


@app.middleware("http")
async def request_guard(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > MAX_REQUEST_BYTES:
        return JSONResponse(
            status_code=413,
            content={"detail": "Request body too large"},
        )

    limit = _rate_limit_for_path(request.url.path)
    if limit:
        now = time.monotonic()
        key = _rate_limit_key(request)
        bucket = _rate_buckets[key]
        while bucket and now - bucket[0] > 60:
            bucket.popleft()
        if len(bucket) >= limit:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please wait a minute and try again."},
                headers={"Retry-After": "60"},
            )
        bucket.append(now)

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}


@app.get("/health/db", include_in_schema=False)
def db_health():
    try:
        with engine.connect() as conn:
            users = conn.execute(text("SELECT COUNT(*) FROM users")).scalar_one()
            questions = conn.execute(text("SELECT COUNT(*) FROM questions")).scalar_one()
        return {"status": "ok", "users": users, "questions": questions}
    except SQLAlchemyError as exc:
        logger.exception("Database health check failed")
        return JSONResponse(
            status_code=500,
            content={"detail": "Database health check failed", "error": str(exc)},
        )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Check Render logs for the traceback."},
    )


# ── Schemas ──────────────────────────────────────────────────────────────────


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class StartQuizRequest(BaseModel):
    topic: Optional[str] = None
    count: Optional[int] = None  # None = all available questions
    time_limit_seconds: Optional[int] = None


class AnswerItem(BaseModel):
    question_id: int
    selected_opt: Optional[str] = None


class SubmitQuizRequest(BaseModel):
    session_id: int
    answers: List[AnswerItem]


class SubmitSingleRequest(BaseModel):
    session_id: int
    question_id: int
    selected_opt: Optional[str] = None


# ── Auth ─────────────────────────────────────────────────────────────────────


@app.post("/auth/register", tags=["auth"])
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == req.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if len(req.password.encode("utf-8")) > 72:
        raise HTTPException(status_code=400, detail="Password cannot be longer than 72 bytes")
    user = User(email=req.email, password_hash=hash_password(req.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token({"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer"}


@app.post("/auth/login", tags=["auth"])
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token({"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer"}


@app.get("/auth/me", tags=["auth"])
def me(current_user: User = Depends(get_current_user)):
    return {"id": current_user.id, "email": current_user.email}


# ── Topics ───────────────────────────────────────────────────────────────────


@app.get("/topics", tags=["quiz"])
def get_topics(db: Session = Depends(get_db)):
    rows = (
        db.query(Question.topic)
        .filter(Question.topic.isnot(None))
        .distinct()
        .order_by(Question.topic)
        .all()
    )
    return [{"topic": r[0]} for r in rows if r[0]]


# ── Quiz ─────────────────────────────────────────────────────────────────────


def _question_payload(q: Question) -> dict:
    """Return question data safe to send to client (no correct answer)."""
    return {
        "id": q.id,
        "scenario": q.scenario,
        "stem": q.stem,
        "options": [o for o in [q.opt_1, q.opt_2, q.opt_3, q.opt_4, q.opt_5] if o],
    }


def _result_payload(q: Question, selected_opt: Optional[str], is_correct: bool) -> dict:
    return {
        "question_id": q.id,
        "scenario": q.scenario,
        "stem": q.stem,
        "options": [o for o in [q.opt_1, q.opt_2, q.opt_3, q.opt_4, q.opt_5] if o],
        "selected_opt": selected_opt,
        "correct_opt": q.correct_opt,
        "is_correct": is_correct,
        "explanation": q.explanation,
        "tagline": q.tagline,
        "images": json.loads(q.images) if q.images else [],
    }


@app.post("/quiz/start", tags=["quiz"])
def start_quiz(
    req: StartQuizRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Question)
    if req.topic:
        query = query.filter(Question.topic == req.topic)

    all_questions = query.all()
    if not all_questions:
        raise HTTPException(status_code=404, detail="No questions found for this filter")

    count = len(all_questions) if req.count is None else min(req.count, len(all_questions))
    selected = random.sample(all_questions, count)

    session = QuizSession(
        user_id=current_user.id,
        topic_filter=req.topic,
        time_limit_seconds=req.time_limit_seconds,
        total=count,
        question_ids=json.dumps([q.id for q in selected]),
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return {
        "session_id": session.id,
        "time_limit_seconds": req.time_limit_seconds,
        "questions": [_question_payload(q) for q in selected],
    }


@app.post("/quiz/submit", tags=["quiz"])
def submit_quiz(
    req: SubmitQuizRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = (
        db.query(QuizSession)
        .filter(QuizSession.id == req.session_id, QuizSession.user_id == current_user.id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.ended_at:
        raise HTTPException(status_code=400, detail="Quiz already submitted")

    valid_ids = set(json.loads(session.question_ids))
    score = 0
    results = []

    for ans in req.answers:
        if ans.question_id not in valid_ids:
            continue
        q = db.query(Question).filter(Question.id == ans.question_id).first()
        if not q:
            continue
        is_correct = ans.selected_opt is not None and ans.selected_opt == q.correct_opt
        if is_correct:
            score += 1
        db.add(
            QuizAnswer(
                session_id=session.id,
                question_id=q.id,
                selected_opt=ans.selected_opt,
                is_correct=is_correct,
            )
        )
        results.append(_result_payload(q, ans.selected_opt, is_correct))

    session.score = score
    session.ended_at = datetime.utcnow()
    db.commit()

    return {"session_id": session.id, "score": score, "total": session.total, "results": results}


@app.post("/quiz/submit-single", tags=["quiz"])
def submit_single(
    req: SubmitSingleRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Practice mode: record one answer and return the correct answer + explanation."""
    session = (
        db.query(QuizSession)
        .filter(QuizSession.id == req.session_id, QuizSession.user_id == current_user.id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    valid_ids = set(json.loads(session.question_ids))
    if req.question_id not in valid_ids:
        raise HTTPException(status_code=400, detail="Question not part of this session")

    # Idempotent: skip if already answered
    existing = (
        db.query(QuizAnswer)
        .filter(QuizAnswer.session_id == req.session_id,
                QuizAnswer.question_id == req.question_id)
        .first()
    )

    q = db.query(Question).filter(Question.id == req.question_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")

    is_correct = req.selected_opt is not None and req.selected_opt == q.correct_opt

    if not existing:
        db.add(QuizAnswer(
            session_id=req.session_id,
            question_id=req.question_id,
            selected_opt=req.selected_opt,
            is_correct=is_correct,
        ))
        db.commit()

    return {
        "is_correct":   is_correct,
        "correct_opt":  q.correct_opt,
        "explanation":  q.explanation,
        "tagline":      q.tagline,
        "images":       json.loads(q.images) if q.images else [],
    }


@app.get("/quiz/{session_id}/results", tags=["quiz"])
def get_results(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = (
        db.query(QuizSession)
        .filter(QuizSession.id == session_id, QuizSession.user_id == current_user.id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    answers = db.query(QuizAnswer).filter(QuizAnswer.session_id == session_id).all()
    results = []
    for ans in answers:
        q = db.query(Question).filter(Question.id == ans.question_id).first()
        if q:
            results.append(_result_payload(q, ans.selected_opt, ans.is_correct))

    return {
        "session_id": session.id,
        "score": session.score,
        "total": session.total,
        "results": results,
    }


@app.get("/history", tags=["quiz"])
def get_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sessions = (
        db.query(QuizSession)
        .filter(QuizSession.user_id == current_user.id, QuizSession.ended_at.isnot(None))
        .order_by(QuizSession.started_at.desc())
        .all()
    )
    return [
        {
            "session_id": s.id,
            "topic_filter": s.topic_filter,
            "started_at": s.started_at.isoformat(),
            "score": s.score,
            "total": s.total,
            "time_limit_seconds": s.time_limit_seconds,
        }
        for s in sessions
    ]


# ── Static files & page routes ───────────────────────────────────────────────


@app.get("/", include_in_schema=False)
def root():
    return FileResponse("static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")
