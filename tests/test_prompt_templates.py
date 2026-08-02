import time
import uuid

from conftest import register_and_login
from fastapi.testclient import TestClient

from apps.gateway.main import app
from apps.gateway.prompts.templating import extract_variables, render_messages

client = TestClient(app)


def _request_with_lock_retry(fn, *, attempts=5, initial_delay=0.05):
    """See tests/test_evaluation.py's copy of this helper: a fresh client.<verb>(...)
    call is a fully independent attempt through a new request-scoped session, so
    retrying the whole call - unlike retrying session.commit() on one already-failed
    session, which SQLAlchemy refuses - safely absorbs a fire-and-forget audit write
    from an earlier request still settling on another connection."""
    delay = initial_delay
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as e:
            if "locked" not in str(e).lower() or attempt == attempts - 1:
                raise
            time.sleep(delay)
            delay *= 2


# ---------------------------------------------------------------------------
# Templating (pure unit tests, no DB/network)
# ---------------------------------------------------------------------------


def test_extract_variables_finds_all_placeholders_deduplicated():
    messages = [
        {"role": "system", "content": "You are a {{role}} assistant for {{company}}."},
        {"role": "user", "content": "Hi, I'm {{company}}'s customer."},
    ]
    assert extract_variables(messages) == ["company", "role"]


def test_extract_variables_handles_multimodal_content():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe this for {{audience}}"},
                {"type": "image_url", "image_url": {"url": "https://x/y.png"}},
            ],
        }
    ]
    assert extract_variables(messages) == ["audience"]


def test_extract_variables_empty_when_no_placeholders():
    assert extract_variables([{"role": "user", "content": "hello"}]) == []


def test_render_messages_substitutes_all_variables():
    messages = [{"role": "system", "content": "You are a {{role}} bot for {{company}}."}]
    rendered, missing = render_messages(messages, {"role": "support", "company": "Acme"})
    assert rendered[0]["content"] == "You are a support bot for Acme."
    assert missing == []


def test_render_messages_reports_missing_variables_and_leaves_placeholder():
    messages = [{"role": "user", "content": "Hi {{name}}, order {{order_id}} shipped."}]
    rendered, missing = render_messages(messages, {"name": "Sam"})
    assert missing == ["order_id"]
    assert rendered[0]["content"] == "Hi Sam, order {{order_id}} shipped."


def test_render_messages_ignores_extra_unused_variables():
    messages = [{"role": "user", "content": "Hi {{name}}"}]
    rendered, missing = render_messages(messages, {"name": "Sam", "unused": "x"})
    assert rendered[0]["content"] == "Hi Sam"
    assert missing == []


def test_render_messages_substitutes_multimodal_text_parts_only():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Hello {{name}}"},
                {"type": "image_url", "image_url": {"url": "https://x/y.png"}},
            ],
        }
    ]
    rendered, missing = render_messages(messages, {"name": "Sam"})
    assert rendered[0]["content"][0]["text"] == "Hello Sam"
    assert rendered[0]["content"][1] == {"type": "image_url", "image_url": {"url": "https://x/y.png"}}
    assert missing == []


def test_render_messages_does_not_mutate_input():
    messages = [{"role": "user", "content": "Hi {{name}}"}]
    render_messages(messages, {"name": "Sam"})
    assert messages[0]["content"] == "Hi {{name}}"


# ---------------------------------------------------------------------------
# CRUD via the HTTP API
# ---------------------------------------------------------------------------


def _create_org():
    org_id, headers = register_and_login(client)
    return {"id": org_id}, headers


def _create_template(org=None, headers=None, **overrides):
    if org is None:
        org, headers = _create_org()
    payload = {
        "organization_id": org["id"],
        "name": "Greeting",
        "messages": [{"role": "system", "content": "You are a {{role}} assistant."}],
        **overrides,
    }
    resp = client.post("/prompt-templates", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return org, headers, resp.json()


def test_create_prompt_template_starts_at_version_1_with_extracted_variables():
    _, _, template = _create_template()
    assert template["current_version"] == 1
    assert template["variables"] == ["role"]


def test_create_prompt_template_rejects_message_missing_role_or_content():
    org, headers = _create_org()
    resp = client.post(
        "/prompt-templates",
        json={"organization_id": org["id"], "name": "Bad", "messages": [{"role": "user"}]},
        headers=headers,
    )
    assert resp.status_code == 422


def test_get_prompt_template():
    _, headers, template = _create_template()
    fetched = client.get(f"/prompt-templates/{template['id']}", headers=headers).json()
    assert fetched["id"] == template["id"]
    assert fetched["name"] == "Greeting"


def test_get_prompt_template_404_for_unknown_id():
    _, headers = _create_org()
    assert client.get(f"/prompt-templates/{uuid.uuid4()}", headers=headers).status_code == 404


def test_list_prompt_templates_scoped_to_organization():
    org_a, headers_a = _create_org()
    org_b, headers_b = _create_org()
    client.post(
        "/prompt-templates",
        json={"organization_id": org_a["id"], "name": "A", "messages": [{"role": "user", "content": "hi"}]},
        headers=headers_a,
    )
    client.post(
        "/prompt-templates",
        json={"organization_id": org_b["id"], "name": "B", "messages": [{"role": "user", "content": "hi"}]},
        headers=headers_b,
    )
    listed = client.get("/prompt-templates", params={"organization_id": org_a["id"]}, headers=headers_a).json()
    assert len(listed) == 1
    assert listed[0]["name"] == "A"

    # org_a's user can't list org_b's templates by asking for org_b's id either.
    cross_org = client.get("/prompt-templates", params={"organization_id": org_b["id"]}, headers=headers_a)
    assert cross_org.status_code == 403


def test_update_metadata_only_does_not_bump_version():
    _, headers, template = _create_template()
    resp = client.patch(f"/prompt-templates/{template['id']}", json={"description": "updated"}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["description"] == "updated"
    assert body["current_version"] == 1


def test_update_messages_bumps_version_and_keeps_history():
    _, headers, template = _create_template()
    new_messages = [{"role": "system", "content": "You are a {{role}} bot for {{company}}."}]
    resp = client.patch(
        f"/prompt-templates/{template['id']}", json={"messages": new_messages, "change_note": "add company var"}, headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_version"] == 2
    assert sorted(body["variables"]) == ["company", "role"]

    versions = client.get(f"/prompt-templates/{template['id']}/versions", headers=headers).json()
    assert [v["version"] for v in versions] == [2, 1]
    assert versions[0]["change_note"] == "add company var"


def test_delete_prompt_template():
    _, headers, template = _create_template()
    # create_prompt_template fires an audit write via fire_and_forget that can still
    # be settling on another connection - see _request_with_lock_retry.
    resp = _request_with_lock_retry(lambda: client.delete(f"/prompt-templates/{template['id']}", headers=headers))
    assert resp.status_code == 200
    assert client.get(f"/prompt-templates/{template['id']}", headers=headers).status_code == 404


# ---------------------------------------------------------------------------
# Version history
# ---------------------------------------------------------------------------


def test_get_specific_version():
    _, headers, template = _create_template()
    client.patch(
        f"/prompt-templates/{template['id']}",
        json={"messages": [{"role": "user", "content": "v2 content"}]},
        headers=headers,
    )
    v1 = client.get(f"/prompt-templates/{template['id']}/versions/1", headers=headers).json()
    assert v1["messages"][0]["content"] == "You are a {{role}} assistant."
    v2 = client.get(f"/prompt-templates/{template['id']}/versions/2", headers=headers).json()
    assert v2["messages"][0]["content"] == "v2 content"


def test_get_unknown_version_404s():
    _, headers, template = _create_template()
    assert client.get(f"/prompt-templates/{template['id']}/versions/99", headers=headers).status_code == 404


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


def test_rollback_creates_new_version_with_old_content():
    _, headers, template = _create_template()
    client.patch(
        f"/prompt-templates/{template['id']}",
        json={"messages": [{"role": "user", "content": "v2 content"}]},
        headers=headers,
    )

    resp = client.post(f"/prompt-templates/{template['id']}/rollback", json={"version": 1}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_version"] == 3
    assert body["messages"][0]["content"] == "You are a {{role}} assistant."

    versions = client.get(f"/prompt-templates/{template['id']}/versions", headers=headers).json()
    assert [v["version"] for v in versions] == [3, 2, 1]
    assert "Rolled back to version 1" in versions[0]["change_note"]


def test_rollback_to_unknown_version_404s():
    _, headers, template = _create_template()
    resp = client.post(f"/prompt-templates/{template['id']}/rollback", json={"version": 99}, headers=headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def test_render_endpoint_substitutes_variables():
    _, headers, template = _create_template()
    resp = client.post(f"/prompt-templates/{template['id']}/render", json={"variables": {"role": "support"}}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["messages"][0]["content"] == "You are a support assistant."
    assert body["variables_used"] == ["role"]


def test_render_endpoint_400s_on_missing_variables():
    _, headers, template = _create_template()
    resp = client.post(f"/prompt-templates/{template['id']}/render", json={"variables": {}}, headers=headers)
    assert resp.status_code == 400
    assert "role" in resp.json()["detail"]


def test_render_endpoint_defaults_to_empty_variables():
    org, headers = _create_org()
    _, _, template = _create_template(org, headers, messages=[{"role": "user", "content": "no vars here"}])
    resp = client.post(f"/prompt-templates/{template['id']}/render", json={}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["messages"][0]["content"] == "no vars here"
