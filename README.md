# elbow-rehab-cloudrun-service-fastapi

Project showing a complete use case with a Cloud Run Service written with a Python module and multiple files. The deployment of service is done with FastApi and Uvicorn.



## Local execution with Docker and gcloud CLI

export PROJECT_ID=rehab-project-480112
export SERVICE_NAME=elbow-rehab-service
export LOCATION=europe-central2
export REPO_NAME=elbow-rehab-cloud

docker buildx build \
 --platform linux/amd64 \
 --no-cache \
 -f elbow_rehab/service/Dockerfile \
 -t europe-central2-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/$SERVICE_NAME:latest \
 --push \
 .

gcloud run deploy $SERVICE_NAME \
  --image europe-central2-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/$SERVICE_NAME:latest \
 --region=$LOCATION \
 --allow-unauthenticated
