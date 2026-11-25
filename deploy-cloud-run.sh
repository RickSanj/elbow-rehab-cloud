#!/bin/bash

# Cloud Run Deployment Script
# Deploys the Elbow Rehab API to Google Cloud Run
# Usage: ./deploy-cloud-run.sh [project-id] [service-name] [region]

set -e

# Configuration
PROJECT_ID=${1:-"YOUR-PROJECT-ID"}
SERVICE_NAME=${2:-"elbow-rehab-api"}
REGION=${3:-"us-central1"}
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}Elbow Rehab - Cloud Run Deployment${NC}"
echo -e "${YELLOW}========================================${NC}"

# Check prerequisites
echo -e "\n${YELLOW}Checking prerequisites...${NC}"

if ! command -v gcloud &> /dev/null; then
    echo -e "${RED}❌ gcloud CLI not found. Install it from: https://cloud.google.com/sdk/docs/install${NC}"
    exit 1
fi

if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker not found. Install it from: https://docker.com${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Prerequisites checked${NC}"

# Set project
echo -e "\n${YELLOW}Setting GCP project to: ${PROJECT_ID}${NC}"
gcloud config set project "${PROJECT_ID}" || {
    echo -e "${RED}❌ Failed to set project. Make sure ${PROJECT_ID} is valid.${NC}"
    exit 1
}

# Get environment variables
echo -e "\n${YELLOW}Reading environment variables...${NC}"

if [ ! -f ".env.production" ]; then
    echo -e "${RED}❌ .env.production file not found!${NC}"
    echo -e "${YELLOW}Copy .env.production.example to .env.production and fill in your values:${NC}"
    echo "cp .env.production.example .env.production"
    exit 1
fi

# Load env vars
set -a
source .env.production
set +a

echo -e "${GREEN}✅ Environment variables loaded${NC}"

# Validate required env vars
REQUIRED_VARS=("DB_USER" "DB_PASS" "DB_NAME" "PROJECT_ID" "LOCATION" "INSTANCE_NAME")
for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        echo -e "${RED}❌ Missing required variable: ${var}${NC}"
        exit 1
    fi
done

# Build Docker image
echo -e "\n${YELLOW}Building Docker image...${NC}"
docker build -t "${IMAGE_NAME}:latest" . || {
    echo -e "${RED}❌ Docker build failed${NC}"
    exit 1
}
echo -e "${GREEN}✅ Docker image built${NC}"

# Test locally (optional)
echo -e "\n${YELLOW}Testing Docker image locally...${NC}"
if docker run --rm -e PYTHONUNBUFFERED=true "${IMAGE_NAME}:latest" python -c "from src.main import app; print('✅ App imports successfully')"; then
    echo -e "${GREEN}✅ Local test passed${NC}"
else
    echo -e "${RED}❌ Local test failed${NC}"
    exit 1
fi

# Push to Container Registry
echo -e "\n${YELLOW}Pushing image to Google Container Registry...${NC}"
docker push "${IMAGE_NAME}:latest" || {
    echo -e "${RED}❌ Docker push failed. Make sure you're authenticated: gcloud auth configure-docker${NC}"
    exit 1
}
echo -e "${GREEN}✅ Image pushed to Container Registry${NC}"

# Deploy to Cloud Run
echo -e "\n${YELLOW}Deploying to Cloud Run...${NC}"
gcloud run deploy "${SERVICE_NAME}" \
    --image "${IMAGE_NAME}:latest" \
    --platform managed \
    --region "${REGION}" \
    --allow-unauthenticated \
    --memory 512Mi \
    --cpu 1 \
    --timeout 3600 \
    --max-instances 10 \
    --set-env-vars="\
DB_USER=${DB_USER},\
DB_PASS=${DB_PASS},\
DB_NAME=${DB_NAME},\
PROJECT_ID=${PROJECT_ID},\
LOCATION=${LOCATION},\
INSTANCE_NAME=${INSTANCE_NAME},\
ENVIRONMENT=production,\
DEBUG=false,\
PRIVATE_IP=${PRIVATE_IP:-false}" \
    || {
    echo -e "${RED}❌ Cloud Run deployment failed${NC}"
    exit 1
}

echo -e "${GREEN}✅ Deployment successful!${NC}"

# Get service URL
echo -e "\n${YELLOW}Getting service URL...${NC}"
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
    --region "${REGION}" \
    --format='value(status.url)')

echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}🎉 Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "\n📍 Service URL: ${SERVICE_URL}"
echo -e "\n📋 Next steps:"
echo -e "  1. Update your frontend API URL to: ${SERVICE_URL}"
echo -e "  2. Deploy frontend: firebase deploy --only hosting"
echo -e "  3. Test the application"
echo -e "\n📊 View logs:"
echo -e "  gcloud run services logs read ${SERVICE_NAME} --region ${REGION} --limit=50"
echo -e "\n🔧 View service details:"
echo -e "  gcloud run services describe ${SERVICE_NAME} --region ${REGION}"
echo -e "\n"
