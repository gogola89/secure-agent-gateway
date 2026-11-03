def test_healthz_is_always_ok(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_checks_db_and_redis(client):
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_docs_site_is_served_at_docs(client):
    response = client.get("/docs/", follow_redirects=True)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "secure-agent-gateway" in response.text


def test_swagger_ui_moved_to_api_docs(client):
    assert client.get("/api-docs").status_code == 200


def test_openapi_schema_still_served_at_default_path(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Secure Agent Gateway - Banking API"
