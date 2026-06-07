"""EUREKAI Configuration — Supports both local and cloud deployment."""
import os
import logging

logger = logging.getLogger("ergovision.config")

# ── Base Paths ──────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── File Upload Limits ──────────────────────────────────────────
MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500 MB
MAX_VIDEO_DURATION = 120  # seconds
ALLOWED_EXTENSIONS = {"mp4", "mov", "avi", "mkv", "webm", "wmv", "flv", "m4v"}

# ── Secret Key ──────────────────────────────────────────────────
SECRET_KEY = os.environ.get("SECRET_KEY", "eurekai-dev-key-change-me")

# ── Database (PostgreSQL in cloud, SQLite for local dev) ────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")
SQLITE_PATH = os.path.join(BASE_DIR, "instance", "ergovision.db")

# ── Redis (for background job queue) ────────────────────────────
REDIS_URL = os.environ.get("REDIS_URL", "")

# ── Storage Type: local | s3 | gcs ──────────────────────────────
STORAGE_TYPE = os.environ.get("STORAGE_TYPE", "local")

# ── S3 Configuration (if STORAGE_TYPE=s3) ───────────────────────
AWS_ACCESS_KEY = os.environ.get("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
S3_BUCKET = os.environ.get("S3_BUCKET", "")
S3_PREFIX = os.environ.get("S3_PREFIX", "eurekai")

# ── GCS Configuration (if STORAGE_TYPE=gcs) ─────────────────────
GCS_BUCKET = os.environ.get("GCS_BUCKET", "")
GCS_CREDENTIALS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")

# ── Local Paths ─────────────────────────────────────────────────
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
EVIDENCE_DIR = os.path.join(BASE_DIR, "evidence")
MODEL_DIR = os.path.join(BASE_DIR, "models")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(EVIDENCE_DIR, exist_ok=True)
os.makedirs(MODEL_DIR, exist_ok=True)

# ── Video Processing ────────────────────────────────────────────
TARGET_FPS = 5.0
MAX_VIDEO_DURATION = 120  # seconds
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB

# ── Ergonomic Thresholds ────────────────────────────────────────
RULA_ACTION_THRESHOLD = 4
REBA_ACTION_THRESHOLD = 8

# ── Logging ─────────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger.info("EUREKAI config loaded — storage=%s db=%s",
            STORAGE_TYPE, "PostgreSQL" if DATABASE_URL else "SQLite")


# ── Cloud Storage Helper ────────────────────────────────────────
class StorageBackend:
    """Abstraction for local, S3, or GCS storage."""

    def __init__(self):
        self._s3 = None
        self._gcs = None
        if STORAGE_TYPE == "s3" and S3_BUCKET:
            try:
                import boto3
                self._s3 = boto3.client("s3", region_name=AWS_REGION,
                                        aws_access_key_id=AWS_ACCESS_KEY,
                                        aws_secret_access_key=AWS_SECRET_KEY)
                logger.info("S3 backend initialized: %s", S3_BUCKET)
            except Exception as e:
                logger.error("S3 init failed: %s", e)
        elif STORAGE_TYPE == "gcs" and GCS_BUCKET:
            try:
                from google.cloud import storage
                self._gcs = storage.Client()
                logger.info("GCS backend initialized: %s", GCS_BUCKET)
            except Exception as e:
                logger.error("GCS init failed: %s", e)

    def local_path(self, folder: str, filename: str) -> str:
        """Get local path for a file (always used for processing)."""
        dirs = {"uploads": UPLOAD_DIR, "outputs": OUTPUT_DIR, "evidence": EVIDENCE_DIR}
        d = dirs.get(folder, UPLOAD_DIR)
        return os.path.join(d, filename)

    def save(self, local_path: str, folder: str, filename: str):
        """Upload file to cloud storage if configured."""
        if STORAGE_TYPE == "s3" and self._s3 and S3_BUCKET:
            key = f"{S3_PREFIX}/{folder}/{filename}"
            try:
                self._s3.upload_file(local_path, S3_BUCKET, key)
                logger.debug("Uploaded to S3: %s", key)
            except Exception as e:
                logger.error("S3 upload failed: %s", e)
        elif STORAGE_TYPE == "gcs" and self._gcs and GCS_BUCKET:
            blob_name = f"{S3_PREFIX}/{folder}/{filename}"
            try:
                bucket = self._gcs.bucket(GCS_BUCKET)
                blob = bucket.blob(blob_name)
                blob.upload_from_filename(local_path)
                logger.debug("Uploaded to GCS: %s", blob_name)
            except Exception as e:
                logger.error("GCS upload failed: %s", e)

    def url(self, folder: str, filename: str) -> str:
        """Get public URL for a file."""
        if STORAGE_TYPE == "s3" and S3_BUCKET:
            key = f"{S3_PREFIX}/{folder}/{filename}"
            return f"https://{S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{key}"
        elif STORAGE_TYPE == "gcs" and GCS_BUCKET:
            blob_name = f"{S3_PREFIX}/{folder}/{filename}"
            return f"https://storage.googleapis.com/{GCS_BUCKET}/{blob_name}"
        # Local: return relative URL path
        return f"/video-file/{folder}/{filename}"


# Singleton
storage = StorageBackend()
