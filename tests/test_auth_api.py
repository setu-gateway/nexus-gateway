from fastapi.testclient import TestClient
import pytest

from apps.gateway.auth.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    validate_email_address,
)
from apps.gateway.db.models import User
from apps.gateway.main import app

client = TestClient(app)


def test_auth_full_lifecycle():
    email = "testuser@setu.io"
    password = "securepassword123"

    # 1. Register User
    reg_resp = client.post(
        "/auth/register",
        json={"email": email, "password": password, "organization_name": "Setu Labs"},
    )
    assert reg_resp.status_code == 201
    user_data = reg_resp.json()
    assert user_data["email"] == email
    assert user_data["is_active"] is True

    # Duplicate registration
    dup_resp = client.post("/auth/register", json={"email": email, "password": password})
    assert dup_resp.status_code == 409

    # 2. Login User
    login_resp = client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )
    assert login_resp.status_code == 200
    token_data = login_resp.json()
    access_token = token_data["access_token"]
    refresh_token = token_data["refresh_token"]

    # 3. Get /auth/me with Access Token
    me_resp = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == email

    # 4. Refresh Token
    refresh_resp = client.post(
        "/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_resp.status_code == 200
    new_tokens = refresh_resp.json()
    assert "access_token" in new_tokens

    # 5. Logout User
    logout_resp = client.post(
        "/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert logout_resp.status_code == 200

    # 6. Verify Revoked Token Access Fails
    me_after_logout = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me_after_logout.status_code == 401


async def test_auth_edge_cases(db_session):
    # Invalid Email format
    bad_email_resp = client.post(
        "/auth/register",
        json={"email": "invalid-email-format", "password": "password123"},
    )
    assert bad_email_resp.status_code in (400, 422)

    # Inactive User Login Rejection
    db_session.add(
        User(
            email="inactive@setu.io",
            password_hash=hash_password("password"),
            is_verified=False,
            is_active=False,
        )
    )
    await db_session.commit()

    inactive_login = client.post("/auth/login", json={"email": "inactive@setu.io", "password": "password"})
    assert inactive_login.status_code in (401, 403)

    # Passing Refresh Token to /auth/me (should fail)
    access_token = create_access_token({"sub": "user1", "email": "inactive@setu.io"})
    refresh_token = create_refresh_token({"sub": "user1", "email": "inactive@setu.io"})
    
    me_with_refresh = client.get("/auth/me", headers={"Authorization": f"Bearer {refresh_token}"})
    assert me_with_refresh.status_code == 401

    # Passing Access Token to /auth/refresh (should fail)
    refresh_with_access = client.post("/auth/refresh", json={"refresh_token": access_token})
    assert refresh_with_access.status_code == 400


def test_token_decode_error():
    with pytest.raises(ValueError):
        decode_token("invalid-jwt-token-string")
    assert validate_email_address("not-an-email") is False
