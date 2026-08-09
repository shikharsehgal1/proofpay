from collections.abc import AsyncGenerator
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _normalize_async_database_url(url: str) -> str:
    """Fly Postgres often injects sslmode=disable; asyncpg wants ssl=false."""
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    parsed = urlparse(url)
    q = dict(parse_qsl(parsed.query, keep_blank_values=True))
    # Drop libpq-style params asyncpg doesn't understand cleanly
    q.pop("sslmode", None)
    # Fly internal cast: no TLS
    if "flycast" in (parsed.hostname or "") or "internal" in (parsed.hostname or ""):
        q["ssl"] = "false"
    new_query = urlencode(q)
    return urlunparse(parsed._replace(query=new_query))


settings = get_settings()
_async_url = _normalize_async_database_url(settings.database_url)
engine = create_async_engine(
    _async_url,
    echo=False,
    pool_pre_ping=True,
    connect_args={"ssl": False} if "flycast" in _async_url or "internal" in _async_url else {},
)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
