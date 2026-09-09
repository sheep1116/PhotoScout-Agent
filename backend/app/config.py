from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    dashscope_api_key: SecretStr = SecretStr("")
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_native_base_url: str = "https://dashscope.aliyuncs.com/api/v1"
    qwen_model: str = "qwen3.7-plus"
    amap_web_service_key: SecretStr = SecretStr("")
    amap_base_url: str = "https://restapi.amap.com"
    database_url: str = f"sqlite:///{ROOT / 'photoscout.db'}"
    redis_url: str = ""
    provider_timeout: float = 20
    frontend_origins: list[str] = ["http://127.0.0.1:3000", "http://localhost:3000",
                                  "http://127.0.0.1:3800", "http://localhost:3800"]
    # A live request is an explicit UI action. No paid calls at startup/tests.
    max_search_calls: int = 2

    def public_status(self):
        def configured(key):
            value = key.get_secret_value()
            return bool(value) and not value.startswith("your_")
        return {"dashscope_configured": configured(self.dashscope_api_key),
                "amap_configured": configured(self.amap_web_service_key),
                "model": self.qwen_model, "default_mode": "mock"}
