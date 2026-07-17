from app.config import get_settings

SIGNUP_URL = "/api/v1/auth/signup"
LOGIN_URL = "/api/v1/auth/login"
LOGOUT_URL = "/api/v1/auth/logout"
ME_URL = "/api/v1/auth/me"


def _signup_payload(email="signup@example.com", password="correct horse battery staple"):
    return {
        "email": email,
        "password": password,
        "display_name": "Signup Test",
        "age_attested": True,
        "accept_terms": True,
    }


def test_signup_returns_201_with_user_and_no_password_hash(client):
    response = client.post(SIGNUP_URL, json=_signup_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "signup@example.com"
    assert body["display_name"] == "Signup Test"
    assert body["role"] == "user"
    assert "id" in body
    assert "password_hash" not in body
    assert "password" not in body


def test_signup_duplicate_email_returns_409(client):
    payload = _signup_payload(email="dupe@example.com")
    first = client.post(SIGNUP_URL, json=payload)
    assert first.status_code == 201

    second = client.post(SIGNUP_URL, json=payload)
    assert second.status_code == 409


def test_signup_missing_age_attestation_returns_422(client):
    payload = _signup_payload(email="young@example.com")
    payload["age_attested"] = False

    response = client.post(SIGNUP_URL, json=payload)

    assert response.status_code == 422


def test_signup_missing_terms_acceptance_returns_422(client):
    payload = _signup_payload(email="noterms@example.com")
    payload["accept_terms"] = False

    response = client.post(SIGNUP_URL, json=payload)

    assert response.status_code == 422


def test_login_sets_cookie_and_returns_user(client):
    password = "correct horse battery staple"
    client.post(SIGNUP_URL, json=_signup_payload(email="login@example.com", password=password))

    response = client.post(LOGIN_URL, json={"email": "login@example.com", "password": password})

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "login@example.com"

    settings = get_settings()
    assert settings.session_cookie_name in response.cookies


def test_login_wrong_password_returns_401(client):
    client.post(
        SIGNUP_URL,
        json=_signup_payload(email="wrongpw@example.com", password="rightpassword123"),
    )

    response = client.post(
        LOGIN_URL, json={"email": "wrongpw@example.com", "password": "wrongpassword123"}
    )

    assert response.status_code == 401


def test_me_with_cookie_returns_200(client):
    password = "correct horse battery staple"
    client.post(SIGNUP_URL, json=_signup_payload(email="me@example.com", password=password))
    client.post(LOGIN_URL, json={"email": "me@example.com", "password": password})

    response = client.get(ME_URL)

    assert response.status_code == 200
    assert response.json()["email"] == "me@example.com"


def test_me_without_cookie_returns_401(client):
    response = client.get(ME_URL)

    assert response.status_code == 401


def test_logout_then_me_returns_401(client):
    password = "correct horse battery staple"
    client.post(SIGNUP_URL, json=_signup_payload(email="logout@example.com", password=password))
    client.post(LOGIN_URL, json={"email": "logout@example.com", "password": password})

    logout_response = client.post(LOGOUT_URL)
    assert logout_response.status_code == 204

    me_response = client.get(ME_URL)
    assert me_response.status_code == 401
