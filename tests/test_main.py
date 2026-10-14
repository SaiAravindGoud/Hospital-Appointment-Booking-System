
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200


def test_appointment_routes_exist():
    paths = app.openapi()["paths"]

    assert "/appointments" in paths
    assert "/appointments/my" in paths
    assert "/appointments/{appointment_id}" in paths
    assert "/appointments/{appointment_id}/status" in paths


def test_appointment_status_requires_authentication():
    response = client.patch("/appointments/1/status")
    assert response.status_code == 401


def test_appointment_creation_requires_authentication():
    response = client.post("/appointments", json={})
    assert response.status_code == 401


def test_queue_websocket_routes_exist():
    from app.routers.queue import router

    paths = {route.path for route in router.routes}

    assert "/ws/queue/{doctor_id}" in paths
    assert "/ws/notifications" in paths


def test_call_next_route_exists():
    from app.routers.queue import router

    routes = {
        (route.path, method)
        for route in router.routes
        for method in getattr(route, "methods", set())
    }

    assert ("/doctors/me/call-next", "PUT") in routes


def test_call_next_requires_authentication():
    response = client.put("/doctors/me/call-next")
    assert response.status_code == 401
