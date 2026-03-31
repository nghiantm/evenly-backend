from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database — individual params matching Supabase connection guide
    user: str = "postgres"
    password: str = ""
    host: str = "localhost"
    port: int = 5432
    dbname: str = "postgres"

    # Clerk
    CLERK_JWKS_URL: str = "https://your-clerk-domain.clerk.accounts.dev/.well-known/jwks.json"
    CLERK_ISSUER: str = "https://your-clerk-domain.clerk.accounts.dev"

    # App
    CORS_ORIGINS: List[str] = ["*"]
    DEBUG: bool = False

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.dbname}"


settings = Settings()
