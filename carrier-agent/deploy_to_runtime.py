"""
Deploy Carrier Agent to Vertex AI Agent Runtime with clean requirements.
"""

import os
import sys

CARRIER_DIR = os.path.abspath(os.path.dirname(__file__))
if CARRIER_DIR not in sys.path:
    sys.path.insert(0, CARRIER_DIR)

from google.agents.cli._project import read_project_config
from google.agents.cli.deploy.agent_runtime import deploy_agent_runtime

def main():
    cfg = read_project_config()
    print(f"Deploying project: {cfg.project_name} version: {cfg.version}")
    
    clean_req_path = os.path.join(CARRIER_DIR, "requirements.txt")
    with open(clean_req_path, "w") as f:
        f.write("\n".join([
            "google-adk>=1.14.0,<2.0.0",
            "google-cloud-aiplatform>=1.71.0,<2.0.0",
            "google-cloud-logging>=3.12.0,<4.0.0",
            "google-cloud-vectorsearch>=0.11.0",
            "google-genai>=1.0.0",
            "pydantic>=2.0.0",
            "gcsfs>=2024.11.0"
        ]))
    print(f"Prepared clean requirements at {clean_req_path}")
    
    deploy_agent_runtime(
        cfg=cfg,
        project="genai-demos-391416",
        location="us-central1",
        display_name="carrier-agent",
        requirements_file=clean_req_path,
        no_wait=True
    )

if __name__ == "__main__":
    main()
