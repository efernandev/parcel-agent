from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    ai_provider: Literal["openai", "ollama", "gemini"] = "openai"
    enable_local_ai: bool = False
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: Literal["qwen3:4b", "qwen3:8b", "qwen3:14b"] = "qwen3:8b"
    enable_cloud_ai: bool = False
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    gemini_api_key: str = ""
    gemini_model: str = Field(default="gemini-3.6-flash", pattern=r"^gemini-[a-z0-9.-]+$")
    gmail_credentials_file: Path = ROOT / "credentials.json"
    sync_days: int = Field(default=90, ge=1, le=365)
    sync_limit: int = Field(default=100, ge=1, le=500)
    tailscale_url: str = ""
    tailscale_user: str = ""

    @field_validator("ollama_url")
    @classmethod
    def validate_ollama_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        if (
            parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or not parsed.port or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment
        ):
            raise ValueError("OLLAMA_URL debe ser una URL HTTP local con puerto, como http://127.0.0.1:11434.")
        return value

    @property
    def ai_configuration_error(self) -> str | None:
        if self.ai_provider == "ollama":
            return None if self.enable_local_ai else "Configura ENABLE_LOCAL_AI=true para habilitar Ollama local."
        if self.ai_provider == "gemini":
            if not self.enable_cloud_ai or not self.gemini_api_key:
                return "Configura GEMINI_API_KEY y ENABLE_CLOUD_AI=true antes de sincronizar con Gemini."
            return None
        if not self.enable_cloud_ai or not self.openai_api_key:
            return "Configura OPENAI_API_KEY y ENABLE_CLOUD_AI=true antes de sincronizar con OpenAI."
        return None

    @property
    def ai_configured(self) -> bool:
        return self.ai_configuration_error is None

    @property
    def ai_model(self) -> str:
        if self.ai_provider == "ollama":
            return self.ollama_model
        return self.gemini_model if self.ai_provider == "gemini" else self.openai_model

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