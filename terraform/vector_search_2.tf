# Production Vector Search 2.0 Collection Provisioning
# Uses Google Cloud Vector Search 2.0 (Agent Retrieval) API with dual-vector schema

resource "null_resource" "vector_search_2_collection" {
  triggers = {
    project_id      = var.project_id
    region          = var.region
    collection_name = var.collection_name
  }

  provisioner "local-exec" {
    command = <<EOT
      python3 -c "
import os, sys, requests, google.auth
from google.auth.transport.requests import Request

credentials, project = google.auth.default()
credentials.refresh(Request())
token = credentials.token

url = f'https://${var.region}-vectorsearch.googleapis.com/v1beta1/projects/${var.project_id}/locations/${var.region}/collections?collectionId=${var.collection_name}'
headers = {
    'Authorization': f'Bearer {token}',
    'Content-Type': 'application/json'
}

payload = {
    'displayName': 'Carrier Chiller Technical Documentation & Schematics (Production)',
    'description': 'Production Agent Retrieval index for Carrier commercial chillers (19XR, 23XRV, 30HX, 30RC, 30XV)',
    'dataSchema': {
        'type': 'OBJECT',
        'properties': {
            'chunk_id': {'type': 'STRING'},
            'model_series': {'type': 'STRING'},
            'form_number': {'type': 'STRING'},
            'section': {'type': 'STRING'},
            'page_number': {'type': 'INTEGER'},
            'content_type': {'type': 'STRING'},
            'content': {'type': 'STRING'},
            'has_image': {'type': 'BOOLEAN'},
            'image_url': {'type': 'STRING'},
            'diagram_caption': {'type': 'STRING'},
            'diagram_ocr_details': {'type': 'STRING'}
        }
    },
    'vectorSchema': {
        'text_embedding': {
            'dimension': 768,
            'distanceMeasureType': 'COSINE',
            'autoEmbed': {
                'model': 'publishers/google/models/gemini-embedding-001',
                'taskType': 'QUESTION_ANSWERING',
                'textTemplate': 'Equipment: {model_series} | Manual: {form_number} | Section: {section} | Page: {page_number}\n\nContent:\n{content}'
            }
        },
        'visual_embedding': {
            'dimension': 1408,
            'distanceMeasureType': 'COSINE'
        }
    }
}

resp = requests.post(url, headers=headers, json=payload)
if resp.status_code in (200, 201):
    print(f'[SUCCESS] Vector Search 2.0 Collection ${var.collection_name} created.')
elif 'ALREADY_EXISTS' in resp.text:
    print(f'[INFO] Vector Search 2.0 Collection ${var.collection_name} already exists.')
else:
    print(f'[WARN] Provisioning response ({resp.status_code}): {resp.text}')
"
    EOT
  }
}
