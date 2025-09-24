from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    OLLAMA_URL: str = "http://127.0.0.1:11434"
    DEFAULT_MODEL: str = "llama3"

settings = Settings()