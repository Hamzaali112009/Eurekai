# EUREKAI v5.1 — Cloud Deployment Guide

## Quick Deploy Options

### Option 1: Fly.io (RECOMMENDED — Best for ML apps)

```bash
# 1. Install flyctl
winget install flyctl  # Windows
curl -L https://fly.io/install.sh | sh  # Mac/Linux

# 2. Login
fly auth login

# 3. Create volume for persistent storage
fly volumes create eurekai_data --size 10 --region iad

# 4. Deploy
fly deploy

# 5. Open app
fly open
```

**Cost**: ~$5-10/month (shared CPU + 2GB RAM + 10GB volume)
**Pros**: Fast deploy, persistent volumes, global CDN, good CPU for ML
**Cons**: Requires credit card (even for free tier)

---

### Option 2: Render.com (Easiest setup)

```bash
# 1. Fork/push code to GitHub
# 2. Go to https://dashboard.render.com/blueprints
# 3. Click "New Blueprint Instance"
# 4. Connect your GitHub repo
# 5. Render reads render.yaml and deploys everything automatically
```

**Cost**: ~$7-25/month (web service + PostgreSQL + Redis)
**Pros**: Blueprint auto-deploys DB + Redis + workers, simple UI
**Cons**: Slower CPU for video processing, disk not shared between web + worker

---

### Option 3: Railway.app (Simplest)

```bash
# 1. Install Railway CLI
npm install -g @railway/cli

# 2. Login
railway login

# 3. Initialize project
railway init --name eurekai

# 4. Add PostgreSQL and Redis plugins
railway add --plugin postgres
railway add --plugin redis

# 5. Deploy
railway up

# 6. Get domain
railway domain
```

**Cost**: ~$5-20/month (usage-based)
**Pros**: Zero-config deploy, auto-scaling, easy plugins
**Cons**: Less control over CPU/RAM allocation

---

### Option 4: Docker Compose (Your own VPS / VM)

```bash
# Any VPS: DigitalOcean, Linode, Vultr, AWS EC2, GCP VM, Azure VM

# 1. Install Docker + Docker Compose
# 2. Clone/upload EUREKAI code
# 3. Run:
docker-compose up -d

# 4. Access at http://your-server-ip:5000
```

**Cost**: $5-20/month (VPS)
**Pros**: Full control, persistent storage, cheapest option
**Cons**: You manage the server

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | Yes | Flask secret key (generate random string) |
| `DATABASE_URL` | For cloud | PostgreSQL connection string |
| `REDIS_URL` | For cloud | Redis connection string |
| `STORAGE_TYPE` | No | `local` (default), `s3`, or `gcs` |
| `S3_BUCKET` | If S3 | AWS S3 bucket name |
| `AWS_ACCESS_KEY_ID` | If S3 | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | If S3 | AWS secret key |
| `GCS_BUCKET` | If GCS | Google Cloud Storage bucket |
| `PORT` | No | HTTP port (default 5000) |

---

## Cloud Storage Setup (S3)

For production with multiple servers, use S3 for file storage:

```bash
# 1. Create S3 bucket
aws s3 mb s3://eurekai-uploads

# 2. Set env vars
STORAGE_TYPE=s3
S3_BUCKET=eurekai-uploads
AWS_ACCESS_KEY_ID=your-key
AWS_SECRET_ACCESS_KEY=your-secret
AWS_REGION=us-east-1

# 3. Files auto-upload to S3 after processing
```

---

## Performance Tips

| Issue | Solution |
|-------|----------|
| Video processing slow | Upgrade to 2+ CPU cores, 4GB+ RAM |
| Large video uploads | Set `MAX_FILE_SIZE` and `MAX_VIDEO_DURATION` |
| Disk space full | Use S3/GCS for storage, set up cleanup cron |
| Worker crashes on big videos | Increase gunicorn `--timeout` to 600+ |
| First request slow (cold start) | Use `min_machines_running = 1` on Fly.io |

---

## Free Tier Options

| Platform | Free Tier Limits |
|----------|-----------------|
| **Fly.io** | $5/mo credit (~shared-cpu-1x 24/7) |
| **Render** | Web services sleep after 15min idle |
| **Railway** | $5/mo credit + trial |
| **Google Cloud Run** | 2M requests/mo, 360K CPU-seconds |
| **AWS EC2** | t2.micro 750hrs/mo (1 year free) |
| **Heroku** | No longer has free tier |

**Recommendation**: Start with **Fly.io** ($5 credit covers shared-cpu-1x 24/7) or **Google Cloud Run** (true serverless, pay only for processing time).
