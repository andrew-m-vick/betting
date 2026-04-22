"""Auth smoke tests: signup, login, logout."""


def test_signup_creates_user_and_logs_in(client, db):
    resp = client.post(
        "/auth/signup",
        data={"email": "a@example.com", "password": "hunter2password"},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    from app.models import User

    user = db.session.query(User).filter_by(email="a@example.com").one()
    assert user.password_hash != "hunter2password"


def test_login_with_wrong_password_fails(client, db):
    client.post(
        "/auth/signup",
        data={"email": "b@example.com", "password": "correctpassword"},
    )
    # log out first (signup auto-logs in)
    client.post("/auth/logout")

    resp = client.post(
        "/auth/login",
        data={"email": "b@example.com", "password": "wrongpassword"},
    )
    assert resp.status_code == 200
    assert b"Invalid email or password" in resp.data
