from parcel_agent.store import Store


def parcel(event="available", received_at="2026-11-12T10:00:00+00:00"):
    return {
        "id": "tracking:example:123",
        "title": "Libro",
        "event": event,
        "received_at": received_at,
        "address": "12 rue Exemple, 01210 France",
    }


def test_deduplicates_and_preserves_manual_collection(tmp_path):
    store = Store(tmp_path / "parcels.db")
    store.apply_message("first", [parcel()])
    store.apply_message("reminder", [parcel()])
    assert len(store.pending()) == 1
    assert store.is_processed("first")
    assert store.collect(parcel()["id"])
    store.apply_message("another-reminder", [parcel()])
    assert store.pending() == []
    assert store.collect(parcel()["id"], False)
    assert len(store.pending()) == 1


def test_older_message_cannot_reopen_collected_parcel(tmp_path):
    store = Store(tmp_path / "parcels.db")
    store.apply_message("collected", [parcel("collected")])
    store.apply_message("old", [parcel(received_at="2026-11-11T10:00:00+00:00")])
    assert store.pending() == []


def test_missing_fields_do_not_erase_address(tmp_path):
    store = Store(tmp_path / "parcels.db")
    store.apply_message("first", [parcel()])
    store.apply_message("second", [dict(parcel(), address=None)])
    assert store.pending()[0]["address"] == parcel()["address"]


def test_ai_selection_survives_reopen_without_changing_parcels(tmp_path):
    path = tmp_path / "parcels.db"
    store = Store(path)
    assert store.selected_ai_provider() is None
    store.apply_message("first", [parcel()])
    store.select_ai_provider("gemini")
    reopened = Store(path)
    assert reopened.selected_ai_provider() == "gemini"
    assert len(reopened.pending()) == 1
    reopened.select_ai_provider("gemini")
    assert store.selected_ai_provider() == "gemini"