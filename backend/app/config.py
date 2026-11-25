from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://dock:dock@localhost:5432/dock"
    jwt_secret: str = "dev-secret-change-me"
    # Phase 0: Platzhalter für den angemeldeten Nutzer (Task 0.6). Mit 1.1 auf "0" setzen/entfernen.
    demo_auth: bool = True
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dim: int = 384
    # Entprellung der Neu-Einbettung (T 3.2): Verzögerung des Jobs `reembed` in Sekunden
    reembed_delay_seconds: int = 30


settings = Settings()
