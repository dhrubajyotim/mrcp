from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True)
    number = Column(Integer, unique=True, index=True, nullable=False)
    scenario = Column(Text, nullable=False)
    stem = Column(Text, nullable=False)
    opt_1 = Column(String, nullable=False)
    opt_2 = Column(String, nullable=False)
    opt_3 = Column(String, nullable=True)
    opt_4 = Column(String, nullable=True)
    opt_5 = Column(String, nullable=True)
    correct_opt = Column(String, nullable=False)
    explanation = Column(Text, nullable=False)
    topic = Column(String, nullable=True, index=True)
    tagline = Column(Text, nullable=True)
    images = Column(Text, nullable=True)  # JSON list of relative paths under static/


class QuizSession(Base):
    __tablename__ = "quiz_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    topic_filter = Column(String, nullable=True)
    time_limit_seconds = Column(Integer, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    score = Column(Integer, default=0)
    total = Column(Integer, default=0)
    question_ids = Column(Text, nullable=False)  # JSON array of question IDs


class QuizAnswer(Base):
    __tablename__ = "quiz_answers"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("quiz_sessions.id"), nullable=False)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    selected_opt = Column(String, nullable=True)
    is_correct = Column(Boolean, default=False)
