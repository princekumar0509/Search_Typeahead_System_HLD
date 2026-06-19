"""Application configuration.

All tunables are read from environment variables so the same image can run
in local/dev/prod without code changes (12-factor style).
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed settings loaded from the environment / .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Database -----------------------------------------------------------
    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/typeahead"

    # --- API ----------------------------------------------------------------
    app_name: str = "Search Typeahead System"
    suggestion_limit: int = 10          # max suggestions returned by /suggest
    trending_limit: int = 10            # max queries returned by /trending

    # --- Cache --------------------------------------------------------------
    cache_ttl_seconds: int = 60         # TTL for a cached suggestion entry
    cache_virtual_nodes: int = 150      # virtual nodes per physical node on the ring
    cache_node_names: str = "node1,node2,node3"  # comma separated physical nodes

    # --- Batch writer -------------------------------------------------------
    batch_flush_interval_seconds: float = 30.0  # periodic flush cadence
    batch_flush_threshold: int = 100            # flush early once buffer hits this many distinct queries

    @property
    def cache_nodes(self) -> list[str]:
        """Parsed list of physical cache node names."""
        return [n.strip() for n in self.cache_node_names.split(",") if n.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()
