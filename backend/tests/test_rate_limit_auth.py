from limits import parse

from app import rate_limit

SIGNUP_URL = "/api/v1/auth/signup"
LOGIN_URL = "/api/v1/auth/login"


def _signup_payload(email="signup@example.com", password="correct horse battery staple"):
    return {
        "email": email,
        "password": password,
        "display_name": "Signup Test",
        "age_attested": True,
        "accept_terms": True,
    }


def test_login_per_email_limit_trips_for_same_email_but_not_other_emails(client, monkeypatch):
    monkeypatch.setattr(rate_limit, "LOGIN_EMAIL", parse("2/minute"))

    email = "ratelimited@example.com"
    client.post(SIGNUP_URL, json=_signup_payload(email=email))

    bad_login = {"email": email, "password": "totally-wrong-password"}

    first = client.post(LOGIN_URL, json=bad_login)
    second = client.post(LOGIN_URL, json=bad_login)
    third = client.post(LOGIN_URL, json=bad_login)

    assert first.status_code == 401
    assert second.status_code == 401
    assert third.status_code == 429
    assert "Retry-After" in third.headers

    # A login for a different email must be unaffected (proves per-email keying).
    other_email = "unaffected@example.com"
    client.post(SIGNUP_URL, json=_signup_payload(email=other_email))
    other_response = client.post(
        LOGIN_URL, json={"email": other_email, "password": "totally-wrong-password"}
    )
    assert other_response.status_code == 401


def test_login_per_ip_limit_trips_across_different_emails(client, monkeypatch):
    # Keep the email limit out of the way so only the IP limit can trip.
    monkeypatch.setattr(rate_limit, "LOGIN_EMAIL", parse("1000/minute"))
    monkeypatch.setattr(rate_limit, "LOGIN_IP", parse("2/minute"))

    emails = ["ip-a@example.com", "ip-b@example.com", "ip-c@example.com"]
    for email in emails:
        client.post(SIGNUP_URL, json=_signup_payload(email=email))

    responses = [
        client.post(LOGIN_URL, json={"email": email, "password": "totally-wrong-password"})
        for email in emails
    ]

    assert [r.status_code for r in responses[:2]] == [401, 401]
    assert responses[2].status_code == 429
    assert "Retry-After" in responses[2].headers


def test_signup_per_ip_limit_trips_across_distinct_emails(client, monkeypatch):
    monkeypatch.setattr(rate_limit, "SIGNUP_IP", parse("2/minute"))

    emails = ["signup-a@example.com", "signup-b@example.com", "signup-c@example.com"]
    responses = [client.post(SIGNUP_URL, json=_signup_payload(email=email)) for email in emails]

    assert [r.status_code for r in responses[:2]] == [201, 201]
    assert responses[2].status_code == 429
    assert "Retry-After" in responses[2].headers


def test_single_normal_login_and_signup_succeed_under_real_limits(client):
    password = "correct horse battery staple"
    email = "normal-flow@example.com"

    signup_response = client.post(SIGNUP_URL, json=_signup_payload(email=email, password=password))
    assert signup_response.status_code == 201

    login_response = client.post(LOGIN_URL, json={"email": email, "password": password})
    assert login_response.status_code == 200
