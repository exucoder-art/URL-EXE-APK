import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

class Config:
    BASE_DIR = BASE_DIR  # expose project root on the Config class
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me-in-production-please")
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 16 * 1024 * 1024))  # 16 MB
    UPLOAD_FOLDER = BASE_DIR / os.getenv("UPLOAD_FOLDER", "uploads")
    BUILD_FOLDER = BASE_DIR / os.getenv("BUILD_FOLDER", "builds")
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    BUILD_TIMEOUT_SECONDS = int(os.getenv("BUILD_TIMEOUT_SECONDS", 600))
    MAX_BUILDS_PER_IP_PER_HOUR = int(os.getenv("MAX_BUILDS_PER_IP_PER_HOUR", 5))
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "ico"}
    ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5000").split(",")
    # Simulated build durations (seconds) for demo mode
    APK_BUILD_DURATION = 8
    EXE_BUILD_DURATION = 6

    @staticmethod
    def init_app(app):
        Config.UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
        Config.BUILD_FOLDER.mkdir(parents=True, exist_ok=True)
        (Config.BUILD_FOLDER / "apk").mkdir(exist_ok=True)
        (Config.BUILD_FOLDER / "exe").mkdir(exist_ok=True)
        (Config.UPLOAD_FOLDER / "icons").mkdir(exist_ok=True)
