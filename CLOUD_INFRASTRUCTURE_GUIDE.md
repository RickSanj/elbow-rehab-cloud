# Cloud Infrastructure Deployment Guide

Complete instructions for deploying the Elbow Rehab application to Google Cloud Platform (GCP).

## 🏗️ Current Setup Analysis

### What You Have
```
Backend:        Python FastAPI (src/main.py)
Database:       Google Cloud SQL (PostgreSQL) ✅
Frontend:       React Dashboard + Auth Pages (web/)
Authentication: Firebase ✅
```

### What You Need
```
Backend Server:  Cloud Run or Compute Engine
Frontend Hosting: Cloud Storage + Cloud CDN or Firebase Hosting
CI/CD:           Cloud Build
Monitoring:      Cloud Logging + Cloud Monitoring
```

## 🎯 Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                     USERS (Doctors)                      │
└──────────────────────┬──────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
    ┌───▼───┐      ┌──▼───┐      ┌──▼────┐
    │Firebase│      │CDN   │      │Cloud  │
    │Auth    │      │      │      │Armor  │
    └───────┘      └──────┘      └───────┘
        │              │              │
        └──────────────┼──────────────┘
                       │
        ┌──────────────┴──────────────┐
        │                             │
    ┌───▼──────────────┐      ┌──────▼──────────┐
    │  Frontend         │      │  Backend         │
    │  Cloud Storage    │      │  Cloud Run       │
    │  (React + Auth)   │      │  (FastAPI)       │
    └───────────────────┘      └──────┬───────────┘
                                      │
                               ┌──────▼──────────┐
                               │  Cloud SQL      │
                               │  (PostgreSQL)   │
                               └─────────────────┘
```

## 📋 Deployment Options

### Option A: Cloud Run (Recommended - Simplest) ✅
- **Best for:** Serverless, auto-scaling, pay-per-use
- **Cost:** ~$20-50/month (small usage)
- **Setup time:** 30 minutes
- **Pros:** Easy, automatic scaling, no server management
- **Cons:** Cold start ~2-3 seconds

### Option B: Compute Engine (More Control)
- **Best for:** More control, persistent server
- **Cost:** ~$30-100/month (depending on size)
- **Setup time:** 1 hour
- **Pros:** Full control, no cold start
- **Cons:** Need to manage server

### Option C: App Engine (Middle Ground)
- **Best for:** Quick deployment, managed environment
- **Cost:** ~$25-75/month
- **Setup time:** 20 minutes
- **Pros:** Easy, some control
- **Cons:** Less flexible than Compute Engine

**👉 Recommended: Cloud Run** - Best balance of cost, ease, and performance

---

## 🚀 Option A: Cloud Run Deployment (Recommended)

### Prerequisites

```bash
# 1. Install Google Cloud CLI
# Download from: https://cloud.google.com/sdk/docs/install

# 2. Initialize gcloud
gcloud init

# 3. Set your project
gcloud config set project YOUR-PROJECT-ID

# 4. Authenticate
gcloud auth login
gcloud auth application-default login
```

### Step 1: Prepare Your Code

```bash
# Create .dockerignore
cat > .dockerignore << 'EOF'
.git
.pytest_cache
__pycache__
*.pyc
.env
.venv
node_modules
build
dist
EOF

# Create .gcloudignore (if needed)
cat > .gcloudignore << 'EOF'
.git
.gitignore
EOF
```

### Step 2: Create Dockerfile for Backend

```bash
cat > Dockerfile << 'EOF'
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy code
COPY . .

# Run FastAPI with Gunicorn
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8080", "src.main:app", "--timeout", "120"]
EOF
```

### Step 3: Update requirements.txt

Add gunicorn for production:

```bash
cat >> requirements.txt << 'EOF'
gunicorn==21.2.0
EOF
```

### Step 4: Update your code for Cloud

**Fix environment variables** in `src/main.py`:

```python
import os
from dotenv import load_dotenv

# Load .env only in development
if os.environ.get("ENVIRONMENT") != "production":
    load_dotenv()

# Make sure all env vars are set
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_NAME = os.getenv("DB_NAME")
PROJECT_ID = os.getenv("PROJECT_ID")
# ... etc
```

**Update CORS settings** in `src/main.py`:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",           # Development
        "https://yourdomain.com",          # Production domain
        "https://www.yourdomain.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Step 5: Deploy Backend to Cloud Run

```bash
# Deploy
gcloud run deploy elbow-rehab-api \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars="DB_USER=your_db_user,DB_PASS=your_db_pass,DB_NAME=your_db_name,PROJECT_ID=your_project_id,LOCATION=your_location,INSTANCE_NAME=your_instance_name,ENVIRONMENT=production"

# Get the service URL
gcloud run services describe elbow-rehab-api --region us-central1
```

This gives you a URL like: `https://elbow-rehab-api-xxxxx.run.app`

### Step 6: Build & Deploy Frontend

**Build React app:**

```bash
cd web
npm install
npm run build

# This creates: web/build/ folder with optimized files
```

**Deploy to Firebase Hosting:**

```bash
# Install Firebase CLI
npm install -g firebase-tools

# Login
firebase login

# Initialize Firebase
firebase init hosting

# During init:
# - Select your Firebase project
# - Public directory: web/build
# - Single-page app: Yes
# - Set up redirects: Yes

# Deploy
firebase deploy --only hosting
```

This gives you: `https://your-project.web.app`

### Step 7: Update Frontend API URL

Create `web/.env.production`:

```
REACT_APP_API_URL=https://elbow-rehab-api-xxxxx.run.app
```

Rebuild and redeploy:

```bash
cd web
npm run build
firebase deploy --only hosting
```

### Step 8: Update Backend CORS

Add your Firebase hosting domain to backend CORS:

```python
allow_origins=[
    "https://your-project.web.app",
    "https://your-domain.com",
]
```

Redeploy backend:

```bash
gcloud run deploy elbow-rehab-api --source . --region us-central1
```

---

## 🐳 Option B: Compute Engine Deployment (More Control)

### Step 1: Create VM Instance

```bash
# Create instance
gcloud compute instances create elbow-rehab-vm \
  --image-family=debian-11 \
  --image-project=debian-cloud \
  --machine-type=e2-medium \
  --zone=us-central1-a \
  --tags=http-server,https-server

# SSH into instance
gcloud compute ssh elbow-rehab-vm --zone=us-central1-a
```

### Step 2: Setup on VM

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python
sudo apt install python3 python3-pip python3-venv git -y

# Install Docker (optional, for containerized deployment)
sudo apt install docker.io -y

# Clone your repo
git clone https://github.com/yourname/elbow-rehab-cloud.git
cd elbow-rehab-cloud

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install gunicorn uvicorn
```

### Step 3: Run Backend with Gunicorn

```bash
# Create systemd service
sudo tee /etc/systemd/system/elbow-rehab.service << EOF
[Unit]
Description=Elbow Rehab API
After=network.target

[Service]
Type=notify
User=ubuntu
WorkingDirectory=/home/ubuntu/elbow-rehab-cloud
Environment="PATH=/home/ubuntu/elbow-rehab-cloud/venv/bin"
Environment="DB_USER=your_db_user"
Environment="DB_PASS=your_db_pass"
Environment="DB_NAME=your_db_name"
Environment="PROJECT_ID=your_project_id"
Environment="LOCATION=your_location"
Environment="INSTANCE_NAME=your_instance_name"
ExecStart=/home/ubuntu/elbow-rehab-cloud/venv/bin/gunicorn \
  -w 4 \
  -b 0.0.0.0:8000 \
  src.main:app

[Install]
WantedBy=multi-user.target
EOF

# Start service
sudo systemctl daemon-reload
sudo systemctl start elbow-rehab
sudo systemctl enable elbow-rehab
```

### Step 4: Setup Nginx Reverse Proxy

```bash
# Install Nginx
sudo apt install nginx -y

# Create config
sudo tee /etc/nginx/sites-available/elbow-rehab << 'EOF'
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

# Enable site
sudo ln -s /etc/nginx/sites-available/elbow-rehab /etc/nginx/sites-enabled/

# Test config
sudo nginx -t

# Restart Nginx
sudo systemctl restart nginx
```

### Step 5: Deploy Frontend to VM

```bash
cd web
npm run build

# Copy to Nginx public folder
sudo cp -r build/* /var/www/html/

# Update permissions
sudo chown -R www-data:www-data /var/www/html
```

---

## 🔐 Setup SSL/HTTPS

### Option A: Cloud Run (Automatic)
✅ HTTPS is free and automatic with Cloud Run!

### Option B: Compute Engine (Let's Encrypt)

```bash
# Install Certbot
sudo apt install certbot python3-certbot-nginx -y

# Get certificate
sudo certbot certonly --nginx -d your-domain.com

# Auto-renew
sudo systemctl start certbot.timer
sudo systemctl enable certbot.timer
```

Update Nginx config:

```bash
sudo tee /etc/nginx/sites-available/elbow-rehab << 'EOF'
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

sudo nginx -t
sudo systemctl restart nginx
```

---

## 📊 Database Connection Security

### Current Setup (Should Work in Cloud)
Your code uses Cloud SQL Python Connector:

```python
from google.cloud.sql.connector import Connector, IPTypes

connector = Connector(ip_type=IPTypes.PRIVATE if os.environ.get("PRIVATE_IP") else IPTypes.PUBLIC)
```

### For Production (Cloud Run/VM)

**Option 1: Public IP (Current - Works)**
- ✅ Simpler setup
- ⚠️ Less secure

**Option 2: Private IP (Recommended)**
- ✅ More secure (no public internet)
- ⚠️ Requires VPC setup

Set environment variable:

```bash
# In Cloud Run
gcloud run deploy elbow-rehab-api \
  --set-env-vars="PRIVATE_IP=true,..." \
  ...
```

---

## 🔄 CI/CD Pipeline (Cloud Build)

Automate deployments from GitHub:

### Step 1: Create cloudbuild.yaml

```bash
cat > cloudbuild.yaml << 'EOF'
steps:
  # Build Docker image
  - name: 'gcr.io/cloud-builders/docker'
    args:
      - 'build'
      - '-t'
      - 'gcr.io/$PROJECT_ID/elbow-rehab-api:$SHORT_SHA'
      - '.'

  # Push to Container Registry
  - name: 'gcr.io/cloud-builders/docker'
    args:
      - 'push'
      - 'gcr.io/$PROJECT_ID/elbow-rehab-api:$SHORT_SHA'

  # Deploy to Cloud Run
  - name: 'gcr.io/cloud-builders/gke-deploy'
    args:
      - 'run'
      - '--filename=.'
      - '--image=gcr.io/$PROJECT_ID/elbow-rehab-api:$SHORT_SHA'
      - '--location=us-central1'
      - '--output=/workspace/'

images:
  - 'gcr.io/$PROJECT_ID/elbow-rehab-api:$SHORT_SHA'
  - 'gcr.io/$PROJECT_ID/elbow-rehab-api:latest'

options:
  machineType: 'N1_HIGHCPU_8'

timeout: '1800s'
EOF
```

### Step 2: Connect GitHub

```bash
gcloud builds connect --repository-name=elbow-rehab-cloud \
  --repository-owner=YOUR-GITHUB-USERNAME \
  --region=us-central1
```

Now every push to main automatically deploys! 🚀

---

## 💰 Cost Estimation

### Option A: Cloud Run (Recommended)

```
Monthly Cost Breakdown:
├─ Cloud Run: $20-40 (1M requests/month @ ~$0.0000002/request)
├─ Cloud SQL: $40-80 (db-f1-micro)
├─ Cloud Storage: $0-5 (Frontend assets)
├─ Cloud CDN: $0-10 (Traffic)
└─ Total: ~$60-135/month
```

### Option B: Compute Engine

```
Monthly Cost Breakdown:
├─ VM (e2-medium): $25-40
├─ Cloud SQL: $40-80
├─ Networking: $5-15
└─ Total: ~$70-135/month
```

**Cost Optimization:**
- Use Cloud Run for auto-scaling
- Set Cloud SQL backup schedule
- Use Cloud CDN for frontend
- Monitor with Cloud Monitoring

---

## 📊 Monitoring & Logging

### Cloud Run (Automatic)

View logs:
```bash
gcloud run services logs read elbow-rehab-api --region us-central1
```

### Setup Alerts

```bash
# Create alert policy
gcloud alpha monitoring policies create \
  --notification-channels=CHANNEL_ID \
  --display-name="High Error Rate" \
  --condition-display-name="Error Rate > 5%"
```

### Custom Metrics

In your FastAPI code:

```python
from google.cloud import logging as cloud_logging

# Logging
client = cloud_logging.Client()
client.setup_logging()

logger.error("Something went wrong", extra={
    "user_id": user_id,
    "endpoint": request.url,
})
```

---

## ✅ Deployment Checklist

- [ ] Update CORS settings for your domain
- [ ] Create Dockerfile
- [ ] Update requirements.txt with gunicorn
- [ ] Set environment variables
- [ ] Build and test Docker locally: `docker build -t test . && docker run -p 8000:8000 test`
- [ ] Deploy backend to Cloud Run: `gcloud run deploy ...`
- [ ] Build React app: `npm run build`
- [ ] Deploy to Firebase Hosting: `firebase deploy`
- [ ] Update frontend API URL
- [ ] Test login flow end-to-end
- [ ] Setup monitoring and alerts
- [ ] Configure backups for Cloud SQL
- [ ] Setup CI/CD with Cloud Build

---

## 🧪 Testing Before Production

### Local Testing

```bash
# Test with production settings
export ENVIRONMENT=production
export DB_USER=...
export DB_PASS=...
python -m uvicorn src.main:app --reload --port 8000
```

### Staging Environment

Create separate Cloud Run service for staging:

```bash
gcloud run deploy elbow-rehab-api-staging \
  --source . \
  --region us-central1
```

Test new features on staging before deploying to production.

---

## 🔍 Troubleshooting

### Issue: "Connection refused" to database
**Solution:** Check Cloud SQL instance is running and firewall allows connection

```bash
gcloud sql instances describe YOUR-INSTANCE-NAME
```

### Issue: "CORS error" from frontend
**Solution:** Update CORS in backend + redeploy

```python
allow_origins=["https://your-domain.com"]
```

### Issue: "Permission denied" error
**Solution:** Create service account with proper permissions

```bash
gcloud iam service-accounts create elbow-rehab-api
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member=serviceAccount:elbow-rehab-api@PROJECT_ID.iam.gserviceaccount.com \
  --role=roles/cloudsql.client
```

---

## 📚 Next Steps

1. **Deploy backend** → Follow "Option A: Cloud Run" steps
2. **Deploy frontend** → Build React + Firebase Hosting
3. **Test end-to-end** → Sign up/login on deployed app
4. **Setup monitoring** → Configure alerts
5. **Custom domain** → Point your domain to deployed services
6. **Backup strategy** → Configure Cloud SQL backups

---

## 🆘 Need Help?

- Cloud Run docs: https://cloud.google.com/run/docs
- Cloud SQL docs: https://cloud.google.com/sql/docs
- Firebase Hosting: https://firebase.google.com/docs/hosting
- FastAPI + GCP: https://cloud.google.com/python/docs/reference/storage/latest

---

**Ready to deploy?** Start with Cloud Run - simplest and most cost-effective! 🚀
