def test_healthz_is_always_ok(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_checks_db_and_redis(client):
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
