from parcel_agent.extract import Evidence, Event, Extraction, updates_from
from parcel_agent.gmail import read_message


def message(text):
    return {
        "id": "abc", "thread_id": "thread1", "subject": "Votre colis",
        "text": text, "received_at": "2026-11-12T10:00:00+00:00", "attachments": [],
    }


def event(**fields):
    return Event(**dict({
        "event": "available", "event_quote": "Votre colis est disponible",
        "title": None, "tracking": None, "location": None, "address": None,
        "country": None, "deadline": None, "pickup_code": None,
    }, **fields))


def test_unknown_carrier_and_french_evidence():
    text = "Votre colis est disponible au Relais Exemple, 12 rue Test, France. Jusqu'au 15/11/2026. Code: 123456."
    result = updates_from(Extraction(events=[event(
        address=Evidence(value="12 rue Test", quote="12 rue Test, France"),
        country=Evidence(value="FR", quote="France"),
        deadline=Evidence(value="2026-11-15", quote="Jusqu'au 15/11/2026"),
        pickup_code=Evidence(value="123456", quote="Code: 123456"),
    )]), message(text))[0]
    assert result["address"] == "12 rue Test"
    assert result["country"] == "FR"
    assert result["deadline"] == "2026-11-15"
    assert result["pickup_code"] == "123456"
    assert result["needs_review"]


def test_invented_values_and_dates_are_not_accepted():
    result = updates_from(Extraction(events=[event(
        address=Evidence(value="Geneve", quote="Votre colis est disponible"),
        deadline=Evidence(value="2026-99-45", quote="Votre colis est disponible"),
    )]), message("Votre colis est disponible"))[0]
    assert result["address"] is None
    assert result["deadline"] is None
    assert result["country"] is None


def test_no_event_without_actual_source_evidence():
    assert updates_from(Extraction(events=[event()]), message("En transit")) == []


def test_tracking_merges_different_threads():
    source = message("Votre colis est disponible. Suivi AB123456789FR")
    extraction = Extraction(events=[event(tracking=Evidence(value="AB123456789FR", quote="Suivi AB123456789FR"))])
    first = updates_from(extraction, source)[0]
    second = updates_from(extraction, dict(source, thread_id="different"))[0]
    assert first["id"] == second["id"]
    assert not first["needs_review"]


def test_html_is_text_only_and_inline_images_are_retained():
    import base64

    html = '<head><style>hidden</style></head><p>Ready for pickup</p><script>bad()</script>'
    raw = {
        "id": "a", "threadId": "b", "internalDate": "1794477600000",
        "payload": {"parts": [
            {"mimeType": "text/html", "body": {"data": base64.urlsafe_b64encode(html.encode()).decode()}},
            {"partId": "1", "mimeType": "image/png", "body": {"attachmentId": "xyz"}},
        ]},
    }
    parsed = read_message(raw)
    assert "Ready for pickup" in parsed["text"]
    assert "bad()" not in parsed["text"]
    assert "hidden" not in parsed["text"]
    assert parsed["attachments"][0]["part_id"] == "1"


def test_cloud_disabled_never_sends_email():
    import pytest

    from parcel_agent.config import Settings
    from parcel_agent.extract import extract

    with pytest.raises(ValueError, match="ENABLE_CLOUD_AI"):
        extract(message("Private email"), Settings(_env_file=None, enable_cloud_ai=False))


def test_long_email_without_pickup_cue_is_marked_ignorable_before_ai_call():
    import pytest

    from parcel_agent.config import Settings
    from parcel_agent.extract import IgnoredLongEmail, extract

    email = message("A personal newsletter about local events. " * 5000)
    settings = Settings(_env_file=None, ai_provider="gemini", enable_cloud_ai=True, gemini_api_key="fake-test-key")

    with pytest.raises(IgnoredLongEmail):
        extract(email, settings)


def test_long_email_with_pickup_cue_stays_pending_with_diagnostic():
    import pytest

    from parcel_agent.config import Settings
    from parcel_agent.extract import extract

    email = message("Your parcel is in transit but now ready for collection. " + "Details. " * 7000)
    settings = Settings(_env_file=None, ai_provider="gemini", enable_cloud_ai=True, gemini_api_key="fake-test-key")

    with pytest.raises(ValueError, match="Correo demasiado largo") as error:
        extract(email, settings)

    assert "60000" in str(error.value)
    assert "Votre colis" in str(error.value)


def test_only_gemini_provider_is_supported():
    import pytest
    from pydantic import ValidationError

    from parcel_agent.config import Settings

    with pytest.raises(ValidationError):
        Settings(_env_file=None, ai_provider="unsupported")


def test_gemini_configuration_requires_key_and_explicit_cloud_permission():
    from parcel_agent.config import Settings

    for fields in [{}, {"gemini_api_key": "fake-test-key"}, {"enable_cloud_ai": True}]:
        settings = Settings(_env_file=None, ai_provider="gemini", **fields)
        assert settings.ai_configured is False
        assert "GEMINI_API_KEY" in settings.ai_configuration_error
    configured = Settings(
        _env_file=None, ai_provider="gemini", enable_cloud_ai=True, gemini_api_key="fake-test-key",
    )
    assert configured.ai_configured is True
    assert configured.ai_model == "gemini-3.6-flash"


def test_gemini_disabled_never_contacts_any_provider(monkeypatch):
    import httpx
    import pytest

    from parcel_agent.config import Settings

    def unexpected_client(**kwargs):
        raise AssertionError("No provider should be contacted")

    monkeypatch.setattr(httpx, "Client", unexpected_client)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        from parcel_agent.extract import extract

        extract(message("Private email"), Settings(_env_file=None, ai_provider="gemini"))


def test_gemini_uses_structured_json_and_keeps_api_key_out_of_url(monkeypatch):
    import httpx
    import json

    from parcel_agent.config import Settings
    from parcel_agent.extract import extract

    original_client = httpx.Client
    calls = []

    def respond(request):
        assert str(request.url) == "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent"
        assert request.headers["x-goog-api-key"] == "fake-test-key"
        assert "fake-test-key" not in str(request.url)
        payload = json.loads(request.content)
        assert payload["generationConfig"]["responseMimeType"] == "application/json"
        assert payload["generationConfig"]["responseJsonSchema"] == Extraction.model_json_schema()
        assert "tools" not in payload
        email = json.loads(payload["contents"][0]["parts"][0]["text"])
        assert "attachments" not in email
        assert "sender" not in email
        calls.append(request.url.host)
        answer = Extraction(events=[event(event_quote=email["body"])])
        text = answer.model_dump_json()
        return httpx.Response(200, json={"candidates": [{
            "finishReason": "STOP", "content": {"parts": [
                {"thought": True, "text": "not the JSON answer"},
                {"text": text[:10]}, {"text": text[10:]},
            ]},
        }]})

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(transport=transport, **kwargs))
    settings = Settings(_env_file=None, ai_provider="gemini", enable_cloud_ai=True, gemini_api_key="fake-test-key")
    for text in ["Votre colis est disponible", "Your parcel is ready for pickup", "Tu paquete esta disponible para recoger"]:
        assert len(extract(message(text), settings)) == 1
    assert calls == ["generativelanguage.googleapis.com"] * 3


def test_gemini_blocked_or_incomplete_responses_are_not_accepted(monkeypatch):
    import httpx
    import pytest

    from parcel_agent.config import Settings
    from parcel_agent.extract import extract

    original_client = httpx.Client
    responses = [
        {"promptFeedback": {"blockReason": "SAFETY"}},
        {"candidates": []},
        {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": '{"events": []}'}]}}]},
        {"candidates": [{"finishReason": "SAFETY"}]},
    ]
    settings = Settings(_env_file=None, ai_provider="gemini", enable_cloud_ai=True, gemini_api_key="fake-test-key")
    for response in responses:
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=response))
        monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(transport=transport, **kwargs))
        with pytest.raises(ValueError, match="Gemini"):
            extract(message("Private email"), settings)


def test_gemini_quota_error_does_not_switch_provider(monkeypatch):
    import httpx
    import pytest

    from parcel_agent.config import Settings
    from parcel_agent.extract import extract

    original_client = httpx.Client
    calls = []

    def unavailable(request):
        calls.append(request.url.host)
        return httpx.Response(429, json={"error": {"message": "private provider details"}})

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(unavailable), **kwargs))
    settings = Settings(
        _env_file=None, ai_provider="gemini", enable_cloud_ai=True, gemini_api_key="fake-test-key",
    )
    with pytest.raises(httpx.HTTPStatusError):
        extract(message("Private email"), settings)
    assert calls == ["generativelanguage.googleapis.com"]