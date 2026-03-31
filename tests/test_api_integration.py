import pytest
from fastapi.testclient import TestClient
from api import app, create_access_token

client = TestClient(app)

@pytest.fixture
def viewer_token():
    # Helper to generate a token for user_type='viewer'
    return create_access_token({
        "user_id": 999,
        "username": "test_viewer",
        "user_type": "viewer",
        "company_id": 1,
    })

@pytest.fixture
def auth_headers(viewer_token):
    return {"Authorization": f"Bearer {viewer_token}"}

def test_health_check():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_create_incident(auth_headers):
    # Deep test: End-to-end incident creation
    payload = {
        "report": "The CMP-01 machine is shaking violently.",
        "reported_by": "test_viewer"
    }
    response = client.post("/api/incidents", json=payload, headers=auth_headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert "incident_id" in data
    assert data["status"] == "OPEN"
    # Should be in clarification phase if machine isn't fully matched, or jump to questions
    
    incident_id = data["incident_id"]

    # Test submitting an answer
    answer_payload = {
        "answer": "Yes, I see oil leaking from the side."
    }
    ans_response = client.post(f"/api/incidents/{incident_id}/answer", json=answer_payload, headers=auth_headers)
    assert ans_response.status_code == 200, ans_response.text
    ans_data = ans_response.json()
    
    # Assert qa history updated
    assert len(ans_data.get("qa_history", [])) > 0

def test_unauthorized_access():
    payload = {
        "report": "Should fail",
        "reported_by": "test"
    }
    response = client.post("/api/incidents", json=payload)
    assert response.status_code == 401

def test_invalid_user_type_for_incident():
    # Only viewers can create incidents from chat
    admin_token = create_access_token({
        "user_id": 1,
        "username": "admin",
        "user_type": "admin",
        "company_id": 1,
    })
    headers = {"Authorization": f"Bearer {admin_token}"}
    payload = {
        "report": "This should be forbidden",
        "reported_by": "admin"
    }
    response = client.post("/api/incidents", json=payload, headers=headers)
    assert response.status_code == 403
    assert "viewer accounts" in response.text
