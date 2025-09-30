import os

try:
    from pydantic_settings import BaseSettings
except ModuleNotFoundError:  # ランタイム環境に依存せず動作させるためのフォールバック
    class BaseSettings:
        """pydantic-settings が無い環境向けの簡易代替。"""

        def __init__(self, **values):
            for name, default in self._defaults().items():
                setattr(self, name, os.getenv(name, default))
            for name, value in values.items():
                setattr(self, name, value)

        @classmethod
        def _defaults(cls):
            return {
                k: v
                for k, v in cls.__dict__.items()
                if k.isupper() and not k.startswith("_")
            }

class Settings(BaseSettings):
    OLLAMA_URL: str = "http://127.0.0.1:11434"
    DEFAULT_MODEL: str = "gpt-oss:20b"


settings = Settings()
