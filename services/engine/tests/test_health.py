from fastapi.testclient import TestClient

from brimline_engine.main import app

client = TestClient(app)


def test_health_reports_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "engine"}


def test_unknown_route_is_404() -> None:
    assert client.get("/no-such-route").status_code == 404
