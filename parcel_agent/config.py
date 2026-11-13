from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    ai_provider: Literal["gemini"] = "gemini"
    enable_cloud_ai: bool = False
    gemini_api_key: str = ""
    gemini_model: str = Field(default="gemini-3.6-flash", pattern=r"^gemini-[a-z0-9.-]+$")
    gmail_credentials_file: Path = ROOT / "credentials.json"
    sync_days: int = Field(default=90, ge=1, le=365)
    sync_limit: int = Field(default=100, ge=1, le=500)
    tailscale_url: str = ""
    tailscale_user: str = ""

    @property
    def ai_configuration_error(self) -> str | None:
        if not self.enable_cloud_ai or not self.gemini_api_key:
            return "Configura GEMINI_API_KEY y ENABLE_CLOUD_AI=true antes de sincronizar con Gemini."
        return None

    @property
    def ai_configured(self) -> bool:
        return self.ai_configuration_error is None

    @property
    def ai_model(self) -> str:
        return self.gemini_model

    @field_validator("tailscale_url")
    @classmethod
    def validate_tailscale_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value:
            return ""
        parsed = urlsplit(value)
        hostname = parsed.hostname or ""
        if (
            parsed.scheme != "https" or not hostname.endswith(".ts.net")
            or len(hostname.split(".")) < 4 or parsed.port != 8443
            or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment
            or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-." for character in hostname)
        ):
            raise ValueError("TAILSCALE_URL debe ser https://equipo.red.ts.net:8443, sin ruta.")
        return f"https://{hostname}:8443"

    @field_validator("tailscale_user")
    @classmethod
    def validate_tailscale_user(cls, value: str) -> str:
        return value.strip().casefold()

    @model_validator(mode="after")
    def require_private_identity(self):
        if bool(self.tailscale_url) != bool(self.tailscale_user):
            raise ValueError("TAILSCALE_URL y TAILSCALE_USER deben configurarse juntos.")
        return self

    @property
    def tailscale_host(self) -> str | None:
        return urlsplit(self.tailscale_url).hostname

    @property
    def credentials_path(self) -> Path:
        return ROOT / self.gmail_credentials_file