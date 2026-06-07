# EUREKAI v5.1 — Cloud Deployment Dockerfile
FROM python:3.10-slim

# System dependencies for OpenCV, MediaPipe, YOLO
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    ffmpeg \
    libopenh264-7 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Add production WSGI server
RUN pip install --no-cache-dir gunicorn psycopg2-binary redis boto3

# Copy application
COPY . .

# Create directories
RUN mkdir -p uploads outputs evidence models instance

# Environment
ENV FLASK_APP=app.py
ENV PYTHONUNBUFFERED=1
ENV PORT=5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${PORT}/ || exit 1

EXPOSE 5000

# Production: use gunicorn
CMD gunicorn -w 2 -b 0.0.0.0:${PORT} --timeout 300 --access-logfile - --error-logfile - app:app
