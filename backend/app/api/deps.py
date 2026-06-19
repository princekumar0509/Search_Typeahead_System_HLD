"""Request-scoped dependency wiring for the API layer.

Builds repositories and services per request from the DB session and the shared
singletons. Keeping construction here means the route handlers stay thin.
"""
from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.cache.distributed_cache import DistributedCache
from app.config import get_settings
from app.database import get_db
from app.repositories.query_repository import QueryRepository
from app.services.dependencies import batch_writer, get_batch_writer, get_cache
from app.services.search_service import SearchService
from app.services.suggestion_service import SuggestionService
from app.services.trending_service import TrendingService

settings = get_settings()


def get_query_repository(db: Session = Depends(get_db)) -> QueryRepository:
    return QueryRepository(db)


def get_suggestion_service(
    repo: QueryRepository = Depends(get_query_repository),
    cache: DistributedCache = Depends(get_cache),
) -> SuggestionService:
    return SuggestionService(repo=repo, cache=cache, limit=settings.suggestion_limit)


def get_search_service(
    cache: DistributedCache = Depends(get_cache),
) -> SearchService:
    return SearchService(batch_writer=get_batch_writer(), cache=cache)


def get_trending_service(
    repo: QueryRepository = Depends(get_query_repository),
) -> TrendingService:
    return TrendingService(repo=repo, limit=settings.trending_limit)
