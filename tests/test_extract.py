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


def test_structured_provider_response_in_english_and_spanish(monkeypatch):
    import httpx

    from parcel_agent.config import Settings
    from parcel_agent.extract import extract

    original_client = httpx.Client
    calls = []

    def respond(request):
        import json

        payload = json.loads(request.content)
        email = json.loads(payload["messages"][1]["content"])
        assert "attachments" not in email
        calls.append(email)
        result = Extraction(events=[event(event_quote=email["body"])])
        return httpx.Response(200, json={"choices": [{"message": {"content": result.model_dump_json()}}]})

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(transport=transport, **kwargs))
    settings = Settings(_env_file=None, enable_cloud_ai=True, openai_api_key="fake-test-key")
    for text in ["Your parcel is ready for pickup", "Tu paquete esta disponible para recoger"]:
        updates = extract(message(text), settings)
        assert len(updates) == 1
        assert updates[0]["event"] == "available"
    assert len(calls) == 2