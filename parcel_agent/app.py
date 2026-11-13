import io
import threading
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx
import segno
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from pydantic import BaseModel, ConfigDict, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from parcel_agent.config import ROOT, Settings
from parcel_agent.extract import IgnoredLongEmail, extract
from parcel_agent.gmail import Gmail
from parcel_agent.store import Store


STATIC = Path(__file__).parent / "static"


class AISelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["gemini"]
    cloud_consent: bool = False


def public_error(error: Exception, ai_provider: str | None = None) -> str:
    if isinstance(error, RefreshError):
        return "La autorizacion de Gmail ha caducado o fue revocada. Vuelve a conectar."
    if isinstance(error, ValidationError):
        return "La IA devolvio datos con un formato no valido. El correo se mantiene sin procesar."
    if ai_provider == "gemini":
        if isinstance(error, httpx.HTTPStatusError):
            code = error.response.status_code
            if code == 429:
                return "Gemini alcanzo una cuota o limite. Revisa Google AI Studio o elige otro modelo; no se cambiara automaticamente."
            if code in {401, 403}:
                return "Gemini rechazo el acceso. Revisa GEMINI_API_KEY, los permisos, la region y las condiciones del servicio."
            if code == 404:
                return "Gemini no encuentra el modelo. Revisa GEMINI_MODEL y su disponibilidad en tu proyecto."
            return f"Gemini devolvio HTTP {code}. Reintenta o selecciona otro proveedor."
        if isinstance(error, httpx.RequestError):
            return "No se pudo contactar con Gemini. Comprueba la conexion y el acceso permitido por tu red."
    if isinstance(error, httpx.HTTPStatusError):
        return f"El proveedor de IA devolvio HTTP {error.response.status_code}. Revisa la clave, el modelo y el saldo."
    if isinstance(error, HttpError):
        return f"Google devolvio HTTP {error.resp.status}. Revisa el acceso a Gmail."
    if isinstance(error, httpx.RequestError):
        return "No se pudo contactar con el proveedor de IA. Comprueba la conexion."
    if isinstance(error, ValueError):
        return str(error)[:250]
    return "No se pudo completar la operacion. Revisa la configuracion y vuelve a intentarlo."


def demo_parcels() -> list[dict[str, Any]]:
    today = date.today()
    examples = [
        ("demo-book", "Libro de fotografia", "Locker · Ferney-Voltaire", "13 chemin du Levant, 01210 Ferney-Voltaire, France", 1, "FR"),
        ("demo-jacket", "Chaqueta de segunda mano", "Punto de recogida · Saint-Genis", "25 rue de Geneve, 01630 Saint-Genis-Pouilly, France", 3, "FR"),
        ("demo-home", "Accesorios para casa", "Punto de recogida · Geneve", "Rue de Lausanne 20, 1201 Geneve, Suisse", 5, "CH"),
    ]
    return [{
        "id": identity, "title": title, "location": location, "address": address,
        "country": country, "deadline": (today + timedelta(days=days)).isoformat(),
        "pickup_code": "DEMO-1234" if index == 1 else None,
        "needs_review": False, "demo": True,
        "attachments": [{"filename": "QR ficticio", "mime_type": "image/png", "demo": True}] if index != 1 else [],
    } for index, (identity, title, location, address, days, country) in enumerate(examples)]


def create_app(settings: Settings | None = None, store: Store | None = None) -> FastAPI:
    settings = settings or Settings()
    store = store or Store(ROOT / "data" / "parcels.db")
    saved_provider = store.selected_ai_provider()
    if saved_provider == "gemini":
        settings = settings.model_copy(update={"ai_provider": saved_provider})
    gmail = Gmail(settings)
    operation_lock = threading.Lock()
    state_lock = threading.Lock()
    job: dict[str, Any] = {"running": False, "processed": 0, "ignored": 0, "failed": 0, "limited": False, "error": None}
    workers: list[threading.Thread] = []

    @asynccontextmanager
    async def lifespan(application):
        yield
        for worker in workers:
            worker.join(timeout=5)

    app = FastAPI(title="Parcel", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    allowed_hosts = ["localhost", "127.0.0.1", "testserver"]
    if settings.tailscale_host:
        allowed_hosts.append(settings.tailscale_host)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    def private_request(request: Request) -> bool:
        return bool(
            request.url.hostname == settings.tailscale_host
            or any(header in request.headers for header in (
                "tailscale-user-login", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto",
            ))
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        if private_request(request) and (
            not settings.tailscale_url or request.url.hostname != settings.tailscale_host
            or request.headers.get("Tailscale-User-Login", "").casefold() != settings.tailscale_user
        ):
            response = Response("Acceso privado no autorizado.", status_code=403)
        else:
            response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        frame_policy = "'self'" if request.url.path.startswith("/api/attachments/") else "'none'"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-src 'self'; "
            f"object-src 'none'; base-uri 'none'; frame-ancestors {frame_policy}; form-action 'self'"
        )
        return response

    def local_action(request: Request):
        if request.headers.get("X-Parcel-Request") != "1":
            raise HTTPException(403, "Solicitud no permitida.")
        origin = request.headers.get("origin")
        expected_origin = settings.tailscale_url if private_request(request) else str(request.base_url).rstrip("/")
        if origin and origin != expected_origin:
            raise HTTPException(403, "Origen no permitido.")

    def snapshot():
        with state_lock:
            return dict(job)

    def update_job(**values):
        with state_lock:
            job.update(values)

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/health")
    def health():
        return {"app": "parcel-agent", "tailscale_url": settings.tailscale_url}

    @app.get("/api/status")
    def status():
        current_settings = settings
        try:
            connected = gmail.connected()
            credential_error = None
        except Exception:
            connected = False
            credential_error = "No se puede acceder al almacen seguro de credenciales del sistema."
        ai_error = current_settings.ai_configuration_error
        options = []
        options.append({
            "provider": "gemini", "model": current_settings.ai_model,
            "configured": current_settings.ai_configured, "label": "Gemini Flash",
        })
        return {
            "gmail_connected": connected,
            "google_configured": settings.credentials_path.is_file(),
            "ai_configured": current_settings.ai_configured,
            "ai_provider": current_settings.ai_provider,
            "ai_model": current_settings.ai_model,
            "ai_options": options,
            "ai_ready": ai_error is None,
            "ai_error": ai_error,
            "credential_error": credential_error,
            "sync": snapshot(),
        }

    @app.post("/api/ai/provider", dependencies=[Depends(local_action)])
    def select_provider(selection: AISelection):
        nonlocal settings
        if not operation_lock.acquire(blocking=False):
            raise HTTPException(409, "Espera a que termine la operacion antes de cambiar de modelo.")
        try:
            if not selection.cloud_consent:
                raise HTTPException(400, "Confirma el envio de correos al proveedor externo antes de seleccionarlo.")
            updated = settings.model_copy(update={"ai_provider": selection.provider})
            store.select_ai_provider(selection.provider)
            settings = updated
            return status()
        finally:
            operation_lock.release()

    @app.get("/api/parcels")
    def parcels():
        return store.pending()

    @app.get("/api/demo")
    def demo():
        return demo_parcels()

    @app.get("/api/demo/qr")
    def demo_qr():
        output = io.BytesIO()
        segno.make("DEMO-ONLY-NOT-A-VALID-PICKUP-CODE", micro=False).save(output, kind="png", scale=8, border=4)
        return Response(output.getvalue(), media_type="image/png")

    @app.post("/api/gmail/connect", dependencies=[Depends(local_action)])
    def connect(request: Request):
        if private_request(request):
            raise HTTPException(403, "Autoriza Gmail desde el navegador del PC en http://127.0.0.1:8765.")
        if not operation_lock.acquire(blocking=False):
            raise HTTPException(409, "Hay otra operacion en curso.")
        try:
            gmail.connect()
            return {"connected": True}
        except Exception as error:
            raise HTTPException(400, public_error(error)) from None
        finally:
            operation_lock.release()

    @app.post("/api/gmail/disconnect", dependencies=[Depends(local_action)])
    def disconnect():
        if not operation_lock.acquire(blocking=False):
            raise HTTPException(409, "Espera a que termine la operacion en curso.")
        try:
            gmail.disconnect()
            return {"connected": False}
        except Exception as error:
            raise HTTPException(400, public_error(error)) from None
        finally:
            operation_lock.release()

    def synchronize():
        try:
            candidates, limited = gmail.candidates(store.is_processed)
            update_job(limited=limited)
            messages = []
            for candidate in candidates:
                if not store.is_processed(candidate["id"]):
                    messages.append(gmail.message(candidate["id"]))
            for message in sorted(messages, key=lambda item: item["received_at"]):
                try:
                    updates = extract(message, settings)
                    store.apply_message(message["id"], updates)
                    with state_lock:
                        job["processed"] += 1
                except IgnoredLongEmail:
                    store.apply_message(message["id"], [])
                    with state_lock:
                        job["ignored"] += 1
                except Exception as error:
                    with state_lock:
                        job["failed"] += 1
                        job["error"] = public_error(error, settings.ai_provider)
                    if isinstance(error, (httpx.HTTPStatusError, httpx.RequestError)):
                        break
        except Exception as error:
            update_job(error=public_error(error))
        finally:
            update_job(running=False)
            operation_lock.release()

    @app.post("/api/sync", status_code=202, dependencies=[Depends(local_action)])
    def sync():
        if not operation_lock.acquire(blocking=False):
            raise HTTPException(409, "Hay otra operacion en curso.")
        try:
            if settings.ai_configuration_error:
                raise HTTPException(400, settings.ai_configuration_error)
            update_job(running=True, processed=0, ignored=0, failed=0, limited=False, error=None,
                       provider=settings.ai_provider, model=settings.ai_model)
            workers[:] = [worker for worker in workers if worker.is_alive()]
            worker = threading.Thread(target=synchronize, daemon=True)
            workers.append(worker)
            worker.start()
        except HTTPException:
            operation_lock.release()
            raise
        except Exception as error:
            update_job(running=False)
            operation_lock.release()
            raise HTTPException(400, public_error(error, settings.ai_provider)) from None
        return snapshot()

    @app.post("/api/parcels/{parcel_id}/collect", dependencies=[Depends(local_action)])
    def collect(parcel_id: str):
        if not store.collect(parcel_id):
            raise HTTPException(404, "Paquete no encontrado.")
        return {"collected": True}

    @app.post("/api/parcels/{parcel_id}/restore", dependencies=[Depends(local_action)])
    def restore(parcel_id: str):
        if not store.collect(parcel_id, False):
            raise HTTPException(404, "Paquete no encontrado.")
        return {"collected": False}

    @app.get("/api/attachments/{message_id}/{part_id}")
    def attachment(message_id: str, part_id: str):
        permitted = any(
            item.get("message_id") == message_id and item.get("part_id") == part_id
            for parcel in store.pending() for item in parcel.get("attachments", [])
        )
        if not permitted:
            raise HTTPException(404, "Adjunto no encontrado en tus recogidas pendientes.")
        try:
            data, mime = gmail.attachment(message_id, part_id)
            extension = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp", "application/pdf": "pdf"}[mime]
            return Response(data, media_type=mime, headers={
                "Content-Disposition": f'inline; filename="recogida.{extension}"',
            })
        except Exception as error:
            raise HTTPException(400, public_error(error)) from None

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()