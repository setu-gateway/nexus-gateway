import uuid
from datetime import datetime, timezone

from apps.gateway.db.models import APIKey, Organization, Project, User


def test_organization_model_instantiation():
    org = Organization(
        name="Acme AI",
        slug="acme-ai",
        plan="enterprise",
    )
    assert org.name == "Acme AI"
    assert org.slug == "acme-ai"
    assert org.plan == "enterprise"


def test_user_model_instantiation():
    org_id = uuid.uuid4()
    user = User(
        email="user@acme.com",
        password_hash="pbkdf2_sha256$hashed_password",
        is_verified=True,
        is_active=True,
        organization_id=org_id,
    )
    assert user.email == "user@acme.com"
    assert user.is_verified is True
    assert user.is_active is True
    assert user.organization_id == org_id


def test_project_model_instantiation():
    org_id = uuid.uuid4()
    project = Project(
        name="Production Gateway",
        organization_id=org_id,
        description="Main production LLM proxy project",
    )
    assert project.name == "Production Gateway"
    assert project.organization_id == org_id
    assert project.description == "Main production LLM proxy project"


def test_api_key_model_instantiation():
    project_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    key = APIKey(
        project_id=project_id,
        hashed_key="sha256_hashed_secret_key",
        expires_at=now,
    )
    assert key.project_id == project_id
    assert key.hashed_key == "sha256_hashed_secret_key"
    assert key.expires_at == now
