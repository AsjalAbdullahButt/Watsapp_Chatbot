import json

from tests.conftest import ALI, VERIFY, post_signed, say, webhook_body


def test_subscription_handshake_returns_challenge(make_client):
    client, _ = make_client([])
    r = client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "12345"})
    assert r.status_code == 200 and r.text == "12345"


def test_subscription_handshake_rejects_wrong_token(make_client):
    client, _ = make_client([])
    r = client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "1"})
    assert r.status_code == 403


def test_unsigned_post_is_rejected(make_client, sender):
    client, llm = make_client([say("hello")])
    r = client.post("/webhook", content=webhook_body("wamid.1"), headers={"Content-Type": "application/json"})
    assert r.status_code == 401
    assert llm.calls == [] and sender.sent == []


def test_wrongly_signed_post_is_rejected(make_client, sender):
    client, _ = make_client([say("hello")])
    r = post_signed(client, webhook_body("wamid.1"), secret="someone-else")
    assert r.status_code == 401 and sender.sent == []


def test_valid_message_gets_one_reply(make_client, sender):
    client, _ = make_client([say("Assalam o alaikum! How can I help?")])
    r = post_signed(client, webhook_body("wamid.1", text="salam"))
    assert r.status_code == 200
    assert sender.sent == [(ALI, "Assalam o alaikum! How can I help?")]


def test_duplicate_delivery_is_processed_once(make_client, sender):
    client, llm = make_client([say("first"), say("second")])
    body = webhook_body("wamid.dup")
    assert post_signed(client, body).status_code == 200
    assert post_signed(client, body).status_code == 200
    assert len(llm.calls) == 1
    assert sender.sent == [(ALI, "first")]


def test_status_events_are_ignored(make_client, sender):
    client, llm = make_client([say("should not be used")])
    payload = {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {"statuses": [{"id": "wamid.9", "status": "read"}]}}]}]}
    assert post_signed(client, json.dumps(payload).encode()).status_code == 200
    assert llm.calls == [] and sender.sent == []


def test_malformed_json_is_rejected(make_client):
    client, _ = make_client([])
    assert post_signed(client, b"{not json").status_code == 400


def test_non_text_message_gets_fixed_reply_without_llm(make_client, sender):
    client, llm = make_client([say("unused")])
    assert post_signed(client, webhook_body("wamid.img", kind="image")).status_code == 200
    assert llm.calls == []
    assert len(sender.sent) == 1 and "text" in sender.sent[0][1]


def test_health_endpoints(make_client):
    client, _ = make_client([])
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").status_code == 200


def test_rate_limit_replies_once_window_exceeded(make_client, sender, settings):
    settings.rate_limit_messages = 2
    client, _ = make_client([])
    for i in range(3):
        assert post_signed(client, webhook_body(f"wamid.rl{i}")).status_code == 200
    assert len(sender.sent) == 3
    assert "too quickly" in sender.sent[-1][1]


def test_oversized_content_length_rejected(make_client):
    client, _ = make_client([])
    r = client.post("/webhook", content=b"x" * (256 * 1024 + 1), headers={"X-Hub-Signature-256": "sha256=0"})
    assert r.status_code == 413


def test_security_headers_present(make_client):
    client, _ = make_client([])
    assert client.get("/health/live").headers["X-Content-Type-Options"] == "nosniff"


def test_non_dev_requires_secrets():
    import pytest
    from app.core.config import Settings
    with pytest.raises(ValueError):
        Settings(_env_file=None, app_env="prod")


def test_sanitize_strips_control_and_bidi():
    from app.whatsapp.inbound import sanitize_text
    assert sanitize_text("hi\u202e\x00 there\u200b") == "hi there"
