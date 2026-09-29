"""
Production Session Service Factory for Google ADK 2.0.
Provides distributed, stateful multi-turn conversational memory for field technicians across
autoscaled Cloud Run instances and Vertex AI Agent Platform Runtime.
"""

import os
import logging
from typing import Optional
from google.adk.sessions import (
    BaseSessionService,
    InMemorySessionService,
    VertexAiSessionService,
    DatabaseSessionService
)

logger = logging.getLogger("carrier_session_service")

def get_session_service() -> BaseSessionService:
    """Factory creating the appropriate ADK 2.0 session service based on environment configuration.

    Options:
    - vertex_ai (Production Default): Uses Vertex AI managed session service in Agent Platform Runtime.
    - database / postgres: Uses DatabaseSessionService connected to Cloud SQL / Memorystore.
    - in_memory (Local Dev): Ephemeral in-memory dictionary.
    """
    session_backend = os.getenv("SESSION_BACKEND", "in_memory").lower()
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "genai-demos-391416")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

    if session_backend == "vertex_ai":
        try:
            logger.info(f"Initializing VertexAiSessionService in {project_id}/{location}...")
            return VertexAiSessionService(project=project_id, location=location)
        except Exception as e:
            logger.warning(f"Could not initialize VertexAiSessionService ({e}). Falling back to InMemorySessionService.")
            return InMemorySessionService()

    elif session_backend in ("database", "sql", "postgres"):
        db_uri = os.getenv("SESSION_DATABASE_URL")
        if not db_uri:
            logger.warning("SESSION_DATABASE_URL not set for DatabaseSessionService. Falling back to InMemorySessionService.")
            return InMemorySessionService()
        logger.info("Initializing DatabaseSessionService...")
        return DatabaseSessionService(db_url=db_uri)

    else:
        logger.info("Using InMemorySessionService (local development mode).")
        return InMemorySessionService()
