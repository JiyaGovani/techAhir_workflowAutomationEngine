import os


class Config:
    DATABASE_PATH = os.getenv("DATABASE_PATH", "workflow_engine.db")
    SECRET_KEY = os.getenv("SECRET_KEY", "development-only-secret")
