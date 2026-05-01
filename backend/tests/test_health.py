from fastapi.testclient import TestClient


def test_health_reports_service_status(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
