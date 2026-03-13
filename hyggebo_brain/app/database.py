"""PostgreSQL connection pool manager using asyncpg.

Manages the asyncpg connection pool lifecycle and provides
helper methods for executing queries and initializing the schema.
"""

import asyncio
import logging
from typing import Optional

import asyncpg

from config import Settings

logger = logging.getLogger(__name__)


class Database:
    """Async PostgreSQL connection pool manager."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._pool: Optional[asyncpg.Pool] = None

    @property
    def pool(self) -> asyncpg.Pool:
        """Get the connection pool, raising if not initialized."""
        if self._pool is None:
            raise RuntimeError("Database pool not initialized. Call connect() first.")
        return self._pool

    @property
    def is_connected(self) -> bool:
        """Check if the pool is connected and usable."""
        return self._pool is not None and not self._pool._closed

    async def connect(self, max_retries: int = 5, retry_delay: float = 3.0) -> None:
        """Create the connection pool with retry logic.

        Args:
            max_retries: Number of connection attempts before giving up.
            retry_delay: Seconds between retries.
        """
        dsn = self.settings.pg_dsn
        for attempt in range(1, max_retries + 1):
            try:
                self._pool = await asyncpg.create_pool(
                    dsn=dsn,
                    min_size=2,
                    max_size=10,
                    command_timeout=30,
                    statement_cache_size=100,
                )
                logger.info("PostgreSQL pool created (attempt %d/%d)", attempt, max_retries)
                return
            except (asyncpg.PostgresError, OSError, asyncio.TimeoutError) as exc:
                logger.warning(
                    "PostgreSQL connection attempt %d/%d failed: %s",
                    attempt, max_retries, exc,
                )
                if attempt < max_retries:
                    await asyncio.sleep(retry_delay)

        raise ConnectionError(
            f"Could not connect to PostgreSQL after {max_retries} attempts"
        )

    async def close(self) -> None:
        """Gracefully close the connection pool."""
        if self._pool is not None and not self._pool._closed:
            await self._pool.close()
            logger.info("PostgreSQL pool closed")
            self._pool = None

    async def execute(self, query: str, *args) -> str:
        """Execute a query and return the status string."""
        async with self.pool.acquire() as conn:
            return await conn.execute(query, *args)

    async def fetch(self, query: str, *args) -> list[asyncpg.Record]:
        """Execute a query and return all rows."""
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args) -> Optional[asyncpg.Record]:
        """Execute a query and return a single row."""
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args):
        """Execute a query and return a single value."""
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *args)
