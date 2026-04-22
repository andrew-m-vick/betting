"""Smoke tests for auth-gated My Bets pages."""


def _signup(client, email="mybets@example.com", password="hunter2password"):
    return client.post("/auth/signup", data={"email": email, "password": password})


def test_my_bets_requires_auth(client):
    resp = client.get("/my-bets/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_my_bets_renders_empty_state_when_authed(client, db):
    _signup(client)
    resp = client.get("/my-bets/")
    assert resp.status_code == 200
    assert b"No bets tracked yet" in resp.data


def test_analytics_json_empty(client, db):
    _signup(client)
    resp = client.get("/my-bets/analytics.json")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["cumulative_pnl"] == []


def test_methodology_renders(client):
    resp = client.get("/methodology")
    assert resp.status_code == 200
    assert b"Expected value" in resp.data or b"Methodology" in resp.data


def test_404_page_renders(client):
    resp = client.get("/nope-does-not-exist")
    assert resp.status_code == 404
    assert b"404" in resp.data
