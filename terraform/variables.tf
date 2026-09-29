variable "project_id" {
  description = "Google Cloud Project ID"
  type        = string
  default     = "genai-demos-391416"
}

variable "region" {
  description = "Primary GCP Region for Agent and Vector Search 2.0"
  type        = string
  default     = "us-central1"
}

variable "collection_name" {
  description = "Vector Search 2.0 (Agent Retrieval) Collection Name"
  type        = string
  default     = "carrier-chiller-docs-prod"
}

variable "raw_manuals_bucket" {
  description = "GCS bucket name for raw Carrier manuals"
  type        = string
  default     = "genai-demos-391416-carrier-manuals-prod"
}

variable "assets_bucket" {
  description = "GCS bucket name for high-resolution WebP schematics and diagrams"
  type        = string
  default     = "genai-demos-391416-carrier-assets-prod"
}
