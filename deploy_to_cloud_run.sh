#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-genai-demos-391416}"
REGION="${GOOGLE_CLOUD_REGION:-us-central1}"
SERVICE_NAME="carrier-chiller-assistant"

echo "=========================================================="
echo "Deploying Carrier Industrial Chiller Specialist to Cloud Run"
echo "Project: $PROJECT_ID | Region: $REGION | Service: $SERVICE_NAME"
echo "=========================================================="

gcloud config set project "$PROJECT_ID"

# Deploy container directly from source using Google Cloud Build & Cloud Run
gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --min-instances 1 \
  --max-instances 10 \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300 \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLOUD_LOCATION=$REGION,VECTOR_SEARCH_COLLECTION=carrier-chiller-docs,GCS_BUCKET_NAME=$PROJECT_ID-carrier-assets,SESSION_BACKEND=in_memory"

echo "=========================================================="
echo "Deployment Complete! Fetching public Cloud Run URL..."
URL=$(gcloud run services describe "$SERVICE_NAME" --region "$REGION" --format="value(status.url)")
echo "App is live at: $URL"
echo "=========================================================="
