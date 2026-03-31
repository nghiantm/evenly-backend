from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database — accepts a full URL or individual params
    DATABASE_URL: Optional[str] = None
    db_user: str = "postgres"
    db_password: str = ""
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "postgres"

    # Clerk
    CLERK_JWKS_URL: str = "https://your-clerk-domain.clerk.accounts.dev/.well-known/jwks.json"
    CLERK_ISSUER: str = "https://your-clerk-domain.clerk.accounts.dev"

    # App
    CORS_ORIGINS: List[str] = ["*"]
    DEBUG: bool = False

    @property
    def database_url(self) -> str:
        return (
            self.DATABASE_URL
            or f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
        )


settings = Settings()
