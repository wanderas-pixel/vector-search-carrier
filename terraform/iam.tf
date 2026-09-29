# Service Account for Cloud Run Ingestion Worker
resource "google_service_account" "ingestion_worker" {
  account_id   = "carrier-ingestion-worker"
  display_name = "Carrier Ingestion Pipeline Worker SA"
}

# Service Account for Vertex AI Agent Runtime Core
resource "google_service_account" "agent_runner" {
  account_id   = "carrier-agent-runner"
  display_name = "Carrier ADK Agent Runtime SA"
}

# Service Account for FastAPI SSE Streaming Gateway
resource "google_service_account" "api_gateway" {
  account_id   = "carrier-api-gateway"
  display_name = "Carrier API Gateway Service SA"
}

# IAM Permissions for Ingestion Worker
resource "google_project_iam_member" "ingestion_docai" {
  project = var.project_id
  role    = "roles/documentai.viewer"
  member  = "serviceAccount:${google_service_account.ingestion_worker.email}"
}

resource "google_project_iam_member" "ingestion_aiplatform" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.ingestion_worker.email}"
}

resource "google_storage_bucket_iam_member" "ingestion_raw_reader" {
  bucket = google_storage_bucket.raw_manuals.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.ingestion_worker.email}"
}

resource "google_storage_bucket_iam_member" "ingestion_assets_writer" {
  bucket = google_storage_bucket.assets.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.ingestion_worker.email}"
}

# IAM Permissions for Agent Runner
resource "google_project_iam_member" "agent_aiplatform" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.agent_runner.email}"
}

resource "google_project_iam_member" "agent_logging" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.agent_runner.email}"
}

# IAM Permissions for API Gateway
resource "google_project_iam_member" "gateway_reasoning" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.api_gateway.email}"
}

resource "google_storage_bucket_iam_member" "gateway_assets_reader" {
  bucket = google_storage_bucket.assets.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.api_gateway.email}"
}
