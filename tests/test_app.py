from fastapi.testclient import TestClient

from parcel_agent.app import create_app
from parcel_agent.config import Settings
from parcel_agent.store import Store


def client(tmp_path):
    return TestClient(create_app(Settings(_env_file=None), Store(tmp_path / "test.db")))


def test_empty_inbox_demo_and_real_qr_image(tmp_path):
    with client(tmp_path) as browser:
        assert browser.get("/").status_code == 200
        assert browser.get("/api/parcels").json() == []
        demo = browser.get("/api/demo").json()
        assert len(demo) == 3
        assert all(item["demo"] for item in demo)
        qr = browser.get("/api/demo/qr")
        assert qr.headers["content-type"] == "image/png"
        assert qr.content.startswith(b"\x89PNG")
        assert browser.get("/api/parcels").json() == []


def test_mutations_require_same_origin_custom_header(tmp_path):
    with client(tmp_path) as browser:
        assert browser.post("/api/sync").status_code == 403
        assert browser.post("/api/sync", headers={"X-Parcel-Request": "1", "Origin": "https://evil.example"}).status_code == 403
        response = browser.post("/api/sync", headers={"X-Parcel-Request": "1"})
        assert response.status_code == 400
        assert "GEMINI_API_KEY" in response.json()["detail"]


def test_security_headers_and_inaccessible_attachments(tmp_path):
    with client(tmp_path) as browser:
        response = browser.get("/")
        assert response.headers["cache-control"] == "no-store"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert browser.get("/api/attachments/arbitrary/0").status_code == 404
        assert browser.get("/", headers={"host": "evil.example"}).status_code == 400


def test_original_pdf_can_be_framed_only_by_our_app(tmp_path, monkeypatch):
    from parcel_agent.gmail import Gmail

    store = Store(tmp_path / "pdf.db")
    store.apply_message("mail1", [{
        "id": "parcel1", "title": "Libro", "event": "available", "received_at": "2026-11-12T10:00:00+00:00",
        "attachments": [{"message_id": "mail1", "part_id": "1", "mime_type": "application/pdf"}],
    }])
    monkeypatch.setattr(Gmail, "attachment", lambda self, message_id, part_id: (b"%PDF-1.4", "application/pdf"))
    with TestClient(create_app(Settings(_env_file=None), store)) as browser:
        response = browser.get("/api/attachments/mail1/1")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert "frame-ancestors 'self'" in response.headers["content-security-policy"]


def test_original_email_link_redirects_to_gmail_thread(tmp_path, monkeypatch):
    from parcel_agent.gmail import Gmail

    store = Store(tmp_path / "source-link.db")
    store.apply_message("mail-123", [{
        "id": "tracking:ABC123456", "title": "Libro", "event": "available",
        "received_at": "2026-11-12T10:00:00+00:00", "message_id": "mail-123",
    }])
    monkeypatch.setattr(Gmail, "thread_id_for_message", lambda self, message_id: "thread-456")

    with TestClient(create_app(Settings(_env_file=None), store)) as browser:
        response = browser.get("/api/gmail/open/mail-123", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "https://mail.google.com/mail/u/0/#all/thread-456"
        assert browser.get("/api/gmail/open/unknown", follow_redirects=False).status_code == 404


def test_sync_pipeline_and_manual_collection(tmp_path, monkeypatch):
    import importlib

    app_module = importlib.import_module("parcel_agent.app")

    class ImmediateWorker:
        def __init__(self, target, daemon):
            self.target = target

        def start(self):
            self.target()

        def is_alive(self):
            return False

        def join(self, timeout=None):
            pass

    store = Store(tmp_path / "sync.db")
    settings = Settings(_env_file=None, enable_cloud_ai=True, gemini_api_key="fake-test-key")
    monkeypatch.setattr(app_module.threading, "Thread", ImmediateWorker)
    monkeypatch.setattr(app_module.Gmail, "candidates", lambda self, processed: ([{"id": "email1"}] if not processed("email1") else [], False))
    monkeypatch.setattr(app_module.Gmail, "message", lambda self, identity: {"id": identity, "received_at": "2026-11-12T10:00:00+00:00"})
    monkeypatch.setattr(app_module, "extract", lambda email, config: [{
        "id": "tracking:ABC123456", "title": "Libro", "event": "available", "received_at": email["received_at"],
    }])
    headers = {"X-Parcel-Request": "1"}
    with TestClient(create_app(settings, store)) as browser:
        assert browser.post("/api/sync", headers=headers).status_code == 202
        assert len(browser.get("/api/parcels").json()) == 1
        assert browser.post("/api/sync", headers=headers).json()["processed"] == 0
        assert browser.post("/api/parcels/tracking:ABC123456/collect", headers=headers).status_code == 200
        assert browser.get("/api/parcels").json() == []
        assert browser.post("/api/parcels/tracking:ABC123456/restore", headers=headers).status_code == 200
        assert len(browser.get("/api/parcels").json()) == 1


def test_sync_counts_and_marks_obviously_irrelevant_long_email(tmp_path, monkeypatch):
    import importlib

    from parcel_agent.extract import IgnoredLongEmail

    app_module = importlib.import_module("parcel_agent.app")

    class ImmediateWorker:
        def __init__(self, target, daemon):
            self.target = target

        def start(self):
            self.target()

        def is_alive(self):
            return False

        def join(self, timeout=None):
            pass

    store = Store(tmp_path / "ignored.db")
    settings = Settings(_env_file=None, ai_provider="gemini", enable_cloud_ai=True, gemini_api_key="fake-test-key")
    monkeypatch.setattr(app_module.threading, "Thread", ImmediateWorker)
    monkeypatch.setattr(app_module.Gmail, "candidates", lambda self, processed: ([{"id": "transit-email"}], False))
    monkeypatch.setattr(app_module.Gmail, "message", lambda self, identity: {
        "id": identity, "received_at": "2026-11-12T10:00:00+00:00",
    })

    def ignore_long_email(email, configuration):
        raise IgnoredLongEmail

    monkeypatch.setattr(app_module, "extract", ignore_long_email)
    with TestClient(create_app(settings, store)) as browser:
        response = browser.post("/api/sync", headers={"X-Parcel-Request": "1"})

    assert response.status_code == 202
    assert response.json()["ignored"] == 1
    assert response.json()["failed"] == 0
    assert store.is_processed("transit-email")


def test_private_access_requires_exact_host_and_owner(tmp_path):
    settings = Settings(
        _env_file=None, tailscale_url="https://pc.personal.ts.net:8443", tailscale_user="owner@example.com",
    )
    with TestClient(create_app(settings, Store(tmp_path / "private.db"))) as browser:
        assert browser.get("/api/health").status_code == 200
        proxy_headers = {"Host": "pc.personal.ts.net:8443", "X-Forwarded-Proto": "https"}
        assert browser.get("/api/parcels", headers=proxy_headers).status_code == 403
        assert browser.get("/api/parcels", headers=dict(proxy_headers, **{"Tailscale-User-Login": "other@example.com"})).status_code == 403
        owner_headers = dict(proxy_headers, **{"Tailscale-User-Login": "owner@example.com"})
        assert browser.get("/api/parcels", headers=owner_headers).status_code == 200
        assert browser.get("/api/parcels", headers=dict(owner_headers, Host="another.personal.ts.net:8443")).status_code == 403
        assert browser.get("/api/parcels", headers={"X-Forwarded-For": "100.100.100.100"}).status_code == 403


def test_private_https_origin_works_without_trusting_forwarded_scheme(tmp_path):
    settings = Settings(
        _env_file=None, tailscale_url="https://pc.personal.ts.net:8443", tailscale_user="owner@example.com",
    )
    headers = {
        "Host": "pc.personal.ts.net:8443", "Tailscale-User-Login": "owner@example.com",
        "Origin": settings.tailscale_url, "X-Parcel-Request": "1",
    }
    with TestClient(create_app(settings, Store(tmp_path / "origin.db"))) as browser:
        response = browser.post("/api/parcels/missing/collect", headers=headers)
        assert response.status_code == 404
        assert browser.post("/api/parcels/missing/collect", headers=dict(headers, Origin="https://evil.example")).status_code == 403
        assert browser.post("/api/gmail/connect", headers=headers).status_code == 403
        assert "PC" in browser.post("/api/gmail/connect", headers=headers).json()["detail"]


def test_local_mode_rejects_forwarded_requests(tmp_path):
    with client(tmp_path) as browser:
        assert browser.get("/api/parcels", headers={"X-Forwarded-Proto": "https"}).status_code == 403


def test_private_settings_reject_public_urls_and_incomplete_identity():
    import pytest
    from pydantic import ValidationError

    for url in ["https://example.com:8443", "http://pc.personal.ts.net:8443", "https://pc.personal.ts.net:8443/path", "https://pc.personal.ts.net"]:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, tailscale_url=url, tailscale_user="owner@example.com")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, tailscale_url="https://pc.personal.ts.net:8443")


def test_status_uses_only_gemini_and_ignores_unknown_saved_provider(tmp_path):
    settings = Settings(_env_file=None)
    store = Store(tmp_path / "legacy-provider.db")
    store.select_ai_provider("legacy-provider")
    with TestClient(create_app(settings, store)) as browser:
        status = browser.get("/api/status").json()

    assert status["ai_provider"] == "gemini"
    assert status["ai_configured"] is False
    assert status["ai_ready"] is False
    assert "GEMINI_API_KEY" in status["ai_error"]
    assert {item["provider"] for item in status["ai_options"]} == {"gemini"}


def test_provider_selection_requires_consent_and_persists(tmp_path):
    settings = Settings(_env_file=None)
    path = tmp_path / "selection.db"
    headers = {"X-Parcel-Request": "1"}
    with TestClient(create_app(settings, Store(path))) as browser:
        assert browser.post("/api/ai/provider", json={"provider": "gemini"}).status_code == 403
        response = browser.post("/api/ai/provider", headers=headers, json={"provider": "gemini"})
        assert response.status_code == 400
        assert browser.get("/api/status").json()["ai_provider"] == "gemini"
        response = browser.post("/api/ai/provider", headers=headers, json={"provider": "gemini", "cloud_consent": True})
        assert response.status_code == 200
        assert response.json()["ai_provider"] == "gemini"
        assert response.json()["ai_ready"] is False
        assert "GEMINI_API_KEY" in response.json()["ai_error"]
        assert browser.get("/api/parcels").json() == []
    with TestClient(create_app(settings, Store(path))) as restarted:
        assert restarted.get("/api/status").json()["ai_provider"] == "gemini"


def test_provider_selection_never_returns_keys_or_accepts_invalid_values(tmp_path):
    settings = Settings(
        _env_file=None, ai_provider="gemini", enable_cloud_ai=True,
        gemini_api_key="fake-private-gemini-key",
    )
    headers = {"X-Parcel-Request": "1"}
    with TestClient(create_app(settings, Store(tmp_path / "secrets.db"))) as browser:
        response = browser.get("/api/status")
        assert "fake-private" not in response.text
        assert {item["provider"] for item in response.json()["ai_options"]} == {"gemini"}
        assert browser.post("/api/ai/provider", headers=headers, json={"provider": "unsupported"}).status_code == 422
        assert browser.post(
            "/api/ai/provider", headers=dict(headers, Origin="https://evil.example"),
            json={"provider": "gemini", "cloud_consent": True},
        ).status_code == 403


def test_cannot_change_provider_during_sync(tmp_path, monkeypatch):
    class HeldWorker:
        def __init__(self, target, daemon):
            self.target = target

        def start(self):
            pass

        def is_alive(self):
            return True

        def join(self, timeout=None):
            pass

    monkeypatch.setattr("parcel_agent.app.threading.Thread", HeldWorker)
    settings = Settings(_env_file=None, ai_provider="gemini", enable_cloud_ai=True, gemini_api_key="fake-test-key")
    headers = {"X-Parcel-Request": "1"}
    with TestClient(create_app(settings, Store(tmp_path / "busy.db"))) as browser:
        assert browser.post("/api/sync", headers=headers).status_code == 202
        response = browser.post("/api/ai/provider", headers=headers, json={
            "provider": "gemini", "cloud_consent": True,
        })
        assert response.status_code == 409
        assert browser.get("/api/status").json()["ai_provider"] == "gemini"


def test_gemini_quota_error_message_contains_no_private_response():
    import httpx

    from parcel_agent.app import public_error

    request = httpx.Request("POST", "https://generativelanguage.googleapis.com/example")
    error = httpx.HTTPStatusError("private provider response", request=request, response=httpx.Response(429))
    result = public_error(error, "gemini")
    assert "cuota" in result
    assert "private" not in result