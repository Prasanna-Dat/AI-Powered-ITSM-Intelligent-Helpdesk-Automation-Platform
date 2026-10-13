"""Test setup: run fully offline (hash embeddings, extractive answers, in-memory MongoDB, mock ServiceNow)."""
import os
import sys
from pathlib import Path

os.environ.update(EMBEDDING_BACKEND="hash", LLM_BACKEND="extractive", MONGODB_URI="", QDRANT_PATH=":memory:", QDRANT_URL="",
                  SERVICENOW_INSTANCE="", SERVICENOW_USER="", SERVICENOW_PASSWORD="")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c
