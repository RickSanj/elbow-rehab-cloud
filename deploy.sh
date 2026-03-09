#!/bin/bash
set -e

echo "Loading environment variables from .env..."
set -a
source .env
set +a

echo "Removing old local image tag..."
docker rmi europe-central2-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${SERVICE_NAME}:latest || true

echo "Building image..."

docker buildx build \
  --platform linux/amd64 \
  -f ./Dockerfile \
  -t europe-central2-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${SERVICE_NAME}:latest \
  --push .

echo "Deploying to Cloud Run..."

gcloud run deploy ${SERVICE_NAME} \
  --image europe-central2-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${SERVICE_NAME}:latest \
  --region=${LOCATION} \
  --allow-unauthenticated \
  --add-cloudsql-instances=${PROJECT_ID}:${LOCATION}:${INSTANCE_NAME} \
  --set-env-vars="^|^\
PROJECT_ID=${PROJECT_ID}|\
LOCATION=${LOCATION}|\
OUTPUT_DATASET=${OUTPUT_DATASET}|\
IMU_READINGS_TABLE=${IMU_READINGS_TABLE}|\
CALCULATED_ANGLES_TABLE=${CALCULATED_ANGLES_TABLE}|\
OUTPUT_TABLE=${IMU_READINGS_TABLE}|\
INSTANCE_NAME=${INSTANCE_NAME}|\
DB_USER=${DB_USER}|\
DB_PASS=${DB_PASS}|\
DB_NAME=${DB_NAME}|\
INSTANCE_UNIX_SOCKET=${INSTANCE_UNIX_SOCKET}"

echo "Done."