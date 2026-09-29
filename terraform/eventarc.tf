# Cloud Run Job for Document AI Ingestion Worker
resource "google_cloud_run_v2_job" "ingestion_job" {
  name     = "carrier-docai-ingestion-worker"
  location = var.region

  template {
    template {
      service_account = google_service_account.ingestion_worker.email

      containers {
        image = "gcr.io/${var.project_id}/carrier-docai-ingestion:latest"
        
        env {
          name  = "GOOGLE_CLOUD_PROJECT"
          value = var.project_id
        }
        env {
          name  = "GOOGLE_CLOUD_REGION"
          value = var.region
        }
        env {
          name  = "CARRIER_ASSETS_BUCKET"
          value = google_storage_bucket.assets.name
        }
        env {
          name  = "VECTOR_SEARCH_COLLECTION"
          value = var.collection_name
        }

        resources {
          limits = {
            cpu    = "4"
            memory = "8Gi"
          }
        }
      }
    }
  }
}

# Eventarc Trigger on GCS Object Finalize (New PDF Upload)
resource "google_eventarc_trigger" "pdf_upload_trigger" {
  name     = "carrier-manual-upload-trigger"
  location = var.region

  matching_criteria {
    attribute = "type"
    value     = "google.cloud.storage.object.v1.finalized"
  }
  matching_criteria {
    attribute = "bucket"
    value     = google_storage_bucket.raw_manuals.name
  }

  destination {
    cloud_run_service {
      service = google_cloud_run_v2_job.ingestion_job.name
      region  = var.region
      path    = "/"
    }
  }

  service_account = google_service_account.ingestion_worker.email
}
