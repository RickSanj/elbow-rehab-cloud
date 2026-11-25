#!/bin/bash
# Build the image and deploy the elbow-rehab-service to Cloud Run.
#
# Reads non-secret settings from .env. DB_PASS is NOT passed as a plain env
# var: Cloud Run reads it from Secret Manager (secret name: $DB_PASS_SECRET,
# default "db-pass"). Firebase Admin and BigQuery use the Cloud Run service
# account (Application Default Credentials); no key file is needed.
set -euo pipefail

echo "Loading environment variables from .env..."
set -a
source .env
set +a

DB_PASS_SECRET=${DB_PASS_SECRET:-db-pass}
RAW_PACKETS_TABLE=${RAW_PACKETS_TABLE:-raw_imu_packets}
ANGLES_V2_TABLE=${ANGLES_V2_TABLE:-angles_v2}
TASKS_QUEUE=${TASKS_QUEUE:-session-processing}
TASKS_LOCATION=${TASKS_LOCATION:-${LOCATION}}
GIT_SHA=$(git rev-parse --short HEAD)
IMAGE="europe-central2-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${SERVICE_NAME}:${GIT_SHA}"

: "${SERVICE_URL:?Set SERVICE_URL in .env (the https://...run.app URL of this service)}"
: "${TASKS_SERVICE_ACCOUNT:?Set TASKS_SERVICE_ACCOUNT in .env (SA that signs Cloud Tasks OIDC tokens)}"

echo "Building ${IMAGE}..."
docker buildx build \
  --platform linux/amd64 \
  -f ./Dockerfile \
  -t "${IMAGE}" \
  --push .

echo "Deploying to Cloud Run..."
gcloud run deploy "${SERVICE_NAME}" \
  --image "${IMAGE}" \
  --region="${LOCATION}" \
  --allow-unauthenticated \
  --memory 2Gi \
  --timeout=1800 \
  --add-cloudsql-instances="${PROJECT_ID}:${LOCATION}:${INSTANCE_NAME}" \
  --set-secrets="DB_PASS=${DB_PASS_SECRET}:latest" \
  --set-env-vars="^|^\
PROJECT_ID=${PROJECT_ID}|\
LOCATION=${LOCATION}|\
OUTPUT_DATASET=${OUTPUT_DATASET}|\
IMU_READINGS_TABLE=${IMU_READINGS_TABLE}|\
CALCULATED_ANGLES_TABLE=${CALCULATED_ANGLES_TABLE}|\
RAW_PACKETS_TABLE=${RAW_PACKETS_TABLE}|\
ANGLES_V2_TABLE=${ANGLES_V2_TABLE}|\
INSTANCE_NAME=${INSTANCE_NAME}|\
DB_USER=${DB_USER}|\
DB_NAME=${DB_NAME}|\
SERVICE_URL=${SERVICE_URL}|\
TASKS_QUEUE=${TASKS_QUEUE}|\
TASKS_LOCATION=${TASKS_LOCATION}|\
TASKS_SERVICE_ACCOUNT=${TASKS_SERVICE_ACCOUNT}|\
GIT_SHA=${GIT_SHA}"

echo "Done."
