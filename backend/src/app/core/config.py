import os
from enum import Enum

from pydantic import SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    APP_NAME: str = "MyPA"
    APP_DESCRIPTION: str | None = "MyPA — multitenant AI-native personal assistant"
    APP_VERSION: str | None = "0.1.0"
    LICENSE_NAME: str | None = None
    CONTACT_NAME: str | None = None
    CONTACT_EMAIL: str | None = None


class CryptSettings(BaseSettings):
    SECRET_KEY: SecretStr = SecretStr("secret-key")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7


class FileLoggerSettings(BaseSettings):
    FILE_LOG_MAX_BYTES: int = 10 * 1024 * 1024
    FILE_LOG_BACKUP_COUNT: int = 5
    FILE_LOG_FORMAT_JSON: bool = True
    FILE_LOG_LEVEL: str = "INFO"

    # Include request ID, path, method, client host, and status code in the file log
    FILE_LOG_INCLUDE_REQUEST_ID: bool = True
    FILE_LOG_INCLUDE_PATH: bool = True
    FILE_LOG_INCLUDE_METHOD: bool = True
    FILE_LOG_INCLUDE_CLIENT_HOST: bool = True
    FILE_LOG_INCLUDE_STATUS_CODE: bool = True


class ConsoleLoggerSettings(BaseSettings):
    CONSOLE_LOG_LEVEL: str = "INFO"
    CONSOLE_LOG_FORMAT_JSON: bool = False

    # Include request ID, path, method, client host, and status code in the console log
    CONSOLE_LOG_INCLUDE_REQUEST_ID: bool = False
    CONSOLE_LOG_INCLUDE_PATH: bool = False
    CONSOLE_LOG_INCLUDE_METHOD: bool = False
    CONSOLE_LOG_INCLUDE_CLIENT_HOST: bool = False
    CONSOLE_LOG_INCLUDE_STATUS_CODE: bool = False


class DatabaseSettings(BaseSettings):
    pass


class PostgresSettings(DatabaseSettings):
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "postgres"
    POSTGRES_SYNC_PREFIX: str = "postgresql://"
    POSTGRES_ASYNC_PREFIX: str = "postgresql+asyncpg://"
    POSTGRES_URL: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def POSTGRES_URI(self) -> str:
        credentials = f"{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
        location = f"{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        return f"{credentials}@{location}"


class FirstUserSettings(BaseSettings):
    ADMIN_NAME: str = "admin"
    ADMIN_EMAIL: str = "admin@admin.com"
    ADMIN_PASSWORD: str = "!Ch4ng3Th1sP4ssW0rd!"


class TestSettings(BaseSettings): ...


class RedisCacheSettings(BaseSettings):
    REDIS_CACHE_HOST: str = "localhost"
    REDIS_CACHE_PORT: int = 6379

    @computed_field  # type: ignore[prop-decorator]
    @property
    def REDIS_CACHE_URL(self) -> str:
        return f"redis://{self.REDIS_CACHE_HOST}:{self.REDIS_CACHE_PORT}"


class ClientSideCacheSettings(BaseSettings):
    CLIENT_CACHE_MAX_AGE: int = 60


class RedisQueueSettings(BaseSettings):
    REDIS_QUEUE_HOST: str = "localhost"
    REDIS_QUEUE_PORT: int = 6379


class EnvironmentOption(str, Enum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"


class EnvironmentSettings(BaseSettings):
    ENVIRONMENT: EnvironmentOption = EnvironmentOption.LOCAL


class CORSSettings(BaseSettings):
    CORS_ORIGINS: list[str] = ["*"]
    CORS_METHODS: list[str] = ["*"]
    CORS_HEADERS: list[str] = ["*"]


class GoogleOAuthSettings(BaseSettings):
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: SecretStr = SecretStr("")
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/google/callback"
    # Where the Google callback redirects the browser after issuing tokens.
    FRONTEND_OAUTH_CALLBACK_URL: str = "http://localhost:3000/auth/callback"


class LlmTierSettings(BaseSettings):
    """Tier = a quality/cost band (high/medium/low), not a specific provider. Each tier
    picks a provider profile; model names for ALL THREE providers are pre-filled per tier
    regardless of which one is actually selected, so flipping *_PROVIDER alone swaps the
    backing model — no other change needed. Defaults are deliberately mixed across
    providers (not all-Anthropic) so the running system actually exercises
    provider-agnosticism, not just supports it in principle — see decisions-log.md."""

    LLM_TIER_HIGH_PROVIDER: str = "anthropic"
    LLM_TIER_HIGH_ANTHROPIC_MODEL: str = "claude-opus-5"
    LLM_TIER_HIGH_OPENAI_MODEL: str = "gpt-5"
    LLM_TIER_HIGH_OLLAMA_MODEL: str = "llama3.1:70b"

    LLM_TIER_MEDIUM_PROVIDER: str = "openai"
    LLM_TIER_MEDIUM_ANTHROPIC_MODEL: str = "claude-sonnet-5"
    LLM_TIER_MEDIUM_OPENAI_MODEL: str = "gpt-5-mini"
    LLM_TIER_MEDIUM_OLLAMA_MODEL: str = "llama3.1:8b"

    LLM_TIER_LOW_PROVIDER: str = "ollama"
    LLM_TIER_LOW_ANTHROPIC_MODEL: str = "claude-haiku-4-5"
    LLM_TIER_LOW_OPENAI_MODEL: str = "gpt-5-nano"
    LLM_TIER_LOW_OLLAMA_MODEL: str = "llama3.1:8b"

    ANTHROPIC_API_KEY: SecretStr = SecretStr("")
    OPENAI_API_KEY: SecretStr = SecretStr("")
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OLLAMA_BASE_URL: str = "http://localhost:11434/v1"
    # Ollama ignores this value's contents, but the OpenAI-compatible adapter always
    # sends an Authorization header — a placeholder avoids a special-cased "no auth"
    # branch just for one provider profile.
    OLLAMA_API_KEY: SecretStr = SecretStr("ollama")


class MemorySettings(BaseSettings):
    EMBEDDING_MODEL_NAME: str = "sentence-transformers/all-MiniLM-L6-v2"
    EMBEDDING_DIMENSION: int = 384  # column type is dimension-fixed at the DB level — a model
    #                                 swap to a different dimension needs a new migration too.
    CONFIDENCE_THRESHOLD: float = 0.7  # decided 2026-08-28, added to code for the first time here.
    MEMORY_RETRIEVAL_TOP_K: int = 5  # no PRD spec — reasonable default, tune later.


class Settings(
    AppSettings,
    PostgresSettings,
    CryptSettings,
    FirstUserSettings,
    TestSettings,
    RedisCacheSettings,
    ClientSideCacheSettings,
    RedisQueueSettings,
    EnvironmentSettings,
    CORSSettings,
    FileLoggerSettings,
    ConsoleLoggerSettings,
    GoogleOAuthSettings,
    LlmTierSettings,
    MemorySettings,
):
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
