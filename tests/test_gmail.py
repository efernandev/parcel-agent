from unittest.mock import MagicMock

from parcel_agent.config import Settings
from parcel_agent.gmail import Gmail
from parcel_agent.gmail import read_message


def test_pagination_skips_processed_messages_and_reaches_older_mail():
    gmail = Gmail(Settings(_env_file=None, sync_limit=2))
    service = MagicMock()
    service.users.return_value.messages.return_value.list.return_value.execute.side_effect = [
        {"messages": [{"id": "processed"}], "nextPageToken": "next"},
        {"messages": [{"id": "old1"}, {"id": "old2"}]},
    ]
    gmail.service = lambda: service
    messages, limited = gmail.candidates(lambda identity: identity == "processed")
    assert [item["id"] for item in messages] == ["old1", "old2"]
    assert not limited


def test_limit_reports_unprocessed_remainder():
    gmail = Gmail(Settings(_env_file=None, sync_limit=1))
    service = MagicMock()
    service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
        "messages": [{"id": "first"}, {"id": "second"}],
    }
    gmail.service = lambda: service
    messages, limited = gmail.candidates(lambda identity: False)
    assert [item["id"] for item in messages] == ["first"]
    assert limited


def test_search_query_includes_pickup_point_delivery_phrases():
    gmail = Gmail(Settings(_env_file=None))
    service = MagicMock()
    service.users.return_value.messages.return_value.list.return_value.execute.return_value = {"messages": []}
    gmail.service = lambda: service

    gmail.candidates(lambda identity: False)

    query = service.users.return_value.messages.return_value.list.call_args.kwargs["q"]
    assert '"delivered to pickup point"' in query
    assert '"déposé en point relais"' in query
    assert '"entregado en punto de recogida"' in query
    assert "delivered" in query
    assert "livré" in query
    assert "entregado" in query


def test_legacy_charset_preserves_french_accents():
    import base64

    text = "Colis disponible jusqu'au 15 novembre, Gen\u00e8ve"
    raw = {
        "id": "a", "threadId": "b", "internalDate": "1794477600000",
        "payload": {
            "mimeType": "text/plain",
            "headers": [{"name": "Content-Type", "value": "text/plain; charset=iso-8859-1"}],
            "body": {"data": base64.urlsafe_b64encode(text.encode("iso-8859-1")).decode()},
        },
    }
    assert read_message(raw)["text"] == text