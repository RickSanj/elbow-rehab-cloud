# elbow-rehab-cloudrun-service-fastapi

## Required files

Make sure the following files exist in the project root:

- credentials.json   # GCP service account key
- .env.local         # Local environment variables

## Build and start the application

```bash
export PROJECT_ID=rehab-project-480112
export SERVICE_NAME=elbow-rehab-service
export LOCATION=europe-central2
export REPO_NAME=elbow-rehab-cloud
export INSTANCE_NAME=rehab-db
export INSTANCE_UNIX_SOCKET=/cloudsql/${PROJECT_ID}:${LOCATION}:${INSTANCE_NAME}
export DB_USER=postgres
export DB_PASS='pTD\qf">dOI,Zh0T'
export DB_NAME=rehab-data
export OUTPUT_DATASET=rehab_data
export OUTPUT_TABLE=imu_readings

docker buildx build \
  --platform linux/amd64 \
  --no-cache \
  -f elbow_rehab/service/Dockerfile \
  -t europe-central2-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${SERVICE_NAME}:latest \
  --push .


gcloud run deploy ${SERVICE_NAME} \
  --image europe-central2-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${SERVICE_NAME}:latest \
  --region=${LOCATION} \
  --allow-unauthenticated \
  --add-cloudsql-instances=${PROJECT_ID}:${LOCATION}:${INSTANCE_NAME} \
  --set-env-vars="^|^\
PROJECT_ID=${PROJECT_ID}|\
LOCATION=${LOCATION}|\
OUTPUT_DATASET=${OUTPUT_DATASET}|\
OUTPUT_TABLE=${OUTPUT_TABLE}|\
DB_USER=${DB_USER}|\
DB_PASS=${DB_PASS}|\
DB_NAME=${DB_NAME}|\
INSTANCE_UNIX_SOCKET=${INSTANCE_UNIX_SOCKET}"
  .
```
