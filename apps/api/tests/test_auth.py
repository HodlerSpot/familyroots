from .conftest import signup


def test_signup_login_me(client):
    signup(client, "parent@example.com", "Pat Parent")

    r = client.post(
        "/auth/login", json={"email": "parent@example.com", "password": "password123"}
    )
    assert r.status_code == 200
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = client.get("/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["email"] == "parent@example.com"
    assert r.json()["display_name"] == "Pat Parent"


def test_duplicate_email_rejected(client):
    signup(client, "parent@example.com")
    r = client.post(
        "/auth/signup",
        json={"email": "parent@example.com", "display_name": "X", "password": "password123"},
    )
    assert r.status_code == 409


def test_wrong_password_rejected(client):
    signup(client, "parent@example.com")
    r = client.post("/auth/login", json={"email": "parent@example.com", "password": "wrongpass1"})
    assert r.status_code == 401


def test_me_requires_auth(client):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
