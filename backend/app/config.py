from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://localhost:5432/smart_roster"  # override via DATABASE_URL
    cors_origins: str = "http://localhost:5173"
    solver_deterministic_time: float = 30.0
    solver_wall_time_limit: float = 60.0
    comp_off_expiry_days: int = 60

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url
        # Hosted providers often hand out postgres:// URLs; use the psycopg 3 driver.
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
