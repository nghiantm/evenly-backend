from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database — individual params matching Supabase connection guide
    db_user: str
    db_password: str
    db_host: str
    db_port: int
    db_name: str

    # Clerk
    CLERK_JWKS_URL: str
    CLERK_ISSUER: str

    # App
    CORS_ORIGINS: List[str] = ["*"]
    DEBUG: bool = False

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"


settings = Settings()
