import os
import tempfile

from app import create_app


def test_app_creates_routes_without_worker():
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": ":memory:",
    })

    rules = {rule.rule for rule in app.url_map.iter_rules()}

    assert "/" in rules
    assert "/workflows/new" in rules
    assert "/api/workflows" in rules
    assert "/api/executions/<int:execution_id>" in rules


def test_create_and_list_workflow_api():
    fd, database_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(database_path)

    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": database_path,
    })
    client = app.test_client()

    response = client.post("/api/workflows", json={
        "name": "Smoke workflow",
        "steps": [{
            "type": "MESSAGE",
            "recipient": "test@example.com",
            "content": "Hello",
        }],
    })

    assert response.status_code == 201
    assert response.get_json()["name"] == "Smoke workflow"

    list_response = client.get("/api/workflows")
    assert list_response.status_code == 200
    assert len(list_response.get_json()) == 1

    os.unlink(database_path)


def test_workflow_form_and_static_builder_are_available():
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": ":memory:",
    })
    client = app.test_client()

    form_response = client.get("/workflows/new")
    assert form_response.status_code == 200
    assert b"step-builder" in form_response.data

    script_response = client.get("/static/workflow-form.js")
    assert script_response.status_code == 200
    assert b"collectSteps" in script_response.data
