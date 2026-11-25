from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://dock:dock@localhost:5432/dock"
    jwt_secret: str = "dev-secret-change-me-please-use-32-bytes-min"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dim: int = 384
    # Entprellung der Neu-Einbettung (T 3.2): Verzögerung des Jobs `reembed` in Sekunden
    reembed_delay_seconds: int = 30


settings = Settings()
