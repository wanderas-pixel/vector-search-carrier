# GCS Bucket for Raw Carrier PDF Manuals (Input Source)
resource "google_storage_bucket" "raw_manuals" {
  name                        = var.raw_manuals_bucket
  location                    = var.region
  uniform_bucket_level_access = true
  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = 365
    }
    action {
      type = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }
}

# GCS Bucket for Rendered WebP Schematics and Visual Assets (CDN Cached)
resource "google_storage_bucket" "assets" {
  name                        = var.assets_bucket
  location                    = var.region
  uniform_bucket_level_access = true

  cors {
    origin          = ["*"]
    method          = ["GET", "HEAD"]
    response_header = ["Content-Type", "Cache-Control"]
    max_age_seconds = 86400
  }
}
