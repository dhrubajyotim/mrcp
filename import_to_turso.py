import argparse
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from database import engine as target_engine
from models import Base, Question, QuizAnswer, QuizSession, User

load_dotenv()


TABLES = [Question, User, QuizSession, QuizAnswer]


def copy_rows(source_session, target_session, model):
    rows = source_session.execute(select(model)).scalars().all()
    for row in rows:
        values = {column.name: getattr(row, column.name) for column in model.__table__.columns}
        target_session.merge(model(**values))
    return len(rows)


def main():
    parser = argparse.ArgumentParser(
        description="Import local SQLite data into the configured target database, such as Turso."
    )
    parser.add_argument(
        "--source",
        default="sqlite:///./mcq.db",
        help="Source SQLAlchemy database URL. Defaults to sqlite:///./mcq.db.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete existing target rows before importing.",
    )
    parser.add_argument(
        "--include-users",
        action="store_true",
        help="Also import users, quiz sessions, and quiz answers. By default only questions are imported.",
    )
    args = parser.parse_args()

    if not os.getenv("TURSO_DATABASE_URL"):
        raise RuntimeError("Set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN before importing to Turso.")

    source_engine = create_engine(args.source, connect_args={"check_same_thread": False})
    SourceSession = sessionmaker(bind=source_engine)
    TargetSession = sessionmaker(bind=target_engine)

    Base.metadata.create_all(bind=target_engine)

    models = TABLES if args.include_users else [Question]

    with SourceSession() as source_session, TargetSession() as target_session:
        if args.replace:
            for model in reversed(models):
                target_session.execute(delete(model))
            target_session.commit()

        for model in models:
            count = copy_rows(source_session, target_session, model)
            print(f"Imported {count} {model.__tablename__} rows")

        target_session.commit()


if __name__ == "__main__":
    main()
