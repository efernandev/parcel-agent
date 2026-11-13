import base64
import json
from collections.abc import Callable
from datetime import datetime, timezone
from email.message import Message
from html.parser import HTMLParser
from typing import Any

import keyring
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from parcel_agent.config import Settings


SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
KEYRING_SERVICE = "parcel-agent.gmail"
KEYRING_ACCOUNT = "personal"
SEARCH_TERMS = (
    '{colis paquet retrait retirer retirer colis "point relais" consigne '
    'parcel package pickup "pick up" locker collected '
    'paquete recogida recoger recogido entrega "mise a disposition" '
    '"mis a disposition" "a disposition" "disponible" "ready for collection"}'
)
ALLOWED_MEDIA = {"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf"}


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "head"}:
            self.hidden += 1
        if tag in {"br", "p", "div", "tr", "li"}:
            self.chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "head"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.chunks.append(data)


def decode_data(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def read_message(raw: dict[str, Any]) -> dict[str, Any]:
    payload = raw.get("payload", {})
    headers = {item["name"].lower(): item["value"] for item in payload.get("headers", [])}
    plain: list[str] = []
    html: list[str] = []
    attachments: list[dict[str, Any]] = []

    def walk(part):
        mime = part.get("mimeType", "")
        body = part.get("body", {})
        if mime in {"text/plain", "text/html"} and body.get("data"):
            mime_headers = Message()
            for header in part.get("headers", []):
                if header["name"].lower() == "content-type":
                    mime_headers["Content-Type"] = header["value"]
                    break
            charset = mime_headers.get_content_charset() or "utf-8"
            decoded = decode_data(body["data"])
            try:
                content = decoded.decode(charset, errors="replace")
            except LookupError:
                content = decoded.decode("utf-8", errors="replace")
            if mime == "text/plain":
                plain.append(content)
            else:
                parser = TextParser()
                parser.feed(content)
                html.append(" ".join(parser.chunks))
        if mime in ALLOWED_MEDIA and (body.get("attachmentId") or body.get("data")):
            attachments.append({
                "part_id": part.get("partId", "0"),
                "filename": part.get("filename") or "Documento de recogida",
                "mime_type": mime,
                "attachment_id": body.get("attachmentId"),
            })
        for child in part.get("parts", []):
            walk(child)

    walk(payload)
    received_at = datetime.fromtimestamp(int(raw["internalDate"]) / 1000, tz=timezone.utc)
    return {
        "id": raw["id"],
        "thread_id": raw["threadId"],
        "received_at": received_at.isoformat(),
        "subject": headers.get("subject", "Sin asunto"),
        "sender": headers.get("from", ""),
        "text": "\n".join(plain or html),
        "attachments": attachments,
    }


class Gmail:
    def __init__(self, settings: Settings):
        self.settings = settings

    def connected(self) -> bool:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT) is not None

    def connect(self) -> None:
        if not self.settings.credentials_path.is_file():
            raise ValueError("Falta credentials.json. Sigue la configuracion de Google del README.")
        flow = InstalledAppFlow.from_client_secrets_file(str(self.settings.credentials_path), SCOPES)
        credentials = flow.run_local_server(
            host="127.0.0.1", port=0, open_browser=True, timeout_seconds=180,
            authorization_prompt_message="Autoriza Gmail en la ventana del navegador.",
            success_message="Gmail conectado. Puedes cerrar esta ventana y volver a Parcel.",
        )
        self._save(credentials)

    def disconnect(self) -> None:
        if self.connected():
            keyring.delete_password(KEYRING_SERVICE, KEYRING_ACCOUNT)

    def _save(self, credentials: Credentials) -> None:
        keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, credentials.to_json())

    def service(self):
        token = keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
        if not token:
            raise ValueError("Conecta Gmail antes de sincronizar.")
        credentials = Credentials.from_authorized_user_info(json.loads(token), SCOPES)
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            self._save(credentials)
        if not credentials.valid:
            raise ValueError("La autorizacion ha caducado. Vuelve a conectar Gmail.")
        return build("gmail", "v1", credentials=credentials, cache_discovery=False)

    def candidates(self, is_processed: Callable[[str], bool]) -> tuple[list[dict[str, Any]], bool]:
        service = self.service()
        messages: list[dict[str, Any]] = []
        page_token = None
        while True:
            page = service.users().messages().list(
                userId="me", q=f"newer_than:{self.settings.sync_days}d {SEARCH_TERMS}",
                maxResults=100, pageToken=page_token,
            ).execute()
            for candidate in page.get("messages", []):
                if not is_processed(candidate["id"]):
                    if len(messages) == self.settings.sync_limit:
                        return messages, True
                    messages.append(candidate)
            page_token = page.get("nextPageToken")
            if not page_token:
                return messages, False

    def message(self, message_id: str) -> dict[str, Any]:
        raw = self.service().users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()
        return read_message(raw)

    def thread_id_for_message(self, message_id: str) -> str:
        raw = self.service().users().messages().get(
            userId="me", id=message_id, format="minimal"
        ).execute()
        return raw["threadId"]

    def attachment(self, message_id: str, part_id: str) -> tuple[bytes, str]:
        service = self.service()
        raw = service.users().messages().get(userId="me", id=message_id, format="full").execute()

        def find(part):
            if part.get("partId", "0") == part_id and part.get("mimeType") in ALLOWED_MEDIA:
                return part
            for child in part.get("parts", []):
                found = find(child)
                if found:
                    return found
            return None

        part = find(raw.get("payload", {}))
        if not part:
            raise ValueError("Adjunto no disponible o formato no permitido.")
        body = part.get("body", {})
        if body.get("size", 0) > 15_000_000:
            raise ValueError("El adjunto supera los 15 MB. Abre el correo original.")
        if body.get("attachmentId"):
            body = service.users().messages().attachments().get(
                userId="me", messageId=message_id, id=body["attachmentId"]
            ).execute()
        data = decode_data(body.get("data", ""))
        if len(data) > 15_000_000:
            raise ValueError("El adjunto supera los 15 MB. Abre el correo original.")
        return data, part["mimeType"]