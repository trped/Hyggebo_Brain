"""PostgreSQL schema initialization with native declarative partitioning."""
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.database import Database

logger = logging.getLogger(__name__)

# ── Core schema DDL ────────────────────────────────────────────────
SCHEMA_SQL = """
-- Enable extensions (already installed globally)
CREATE EXTENSION IF NOT EXISTS vector;

-- Rooms lookup
CREATE TABLE IF NOT EXISTS rooms (
    room_id     TEXT PRIMARY KEY,
    name_da     TEXT NOT NULL,
    name_en     TEXT NOT NULL,
    floor       TEXT NOT NULL DEFAULT 'ground',
    zone        TEXT NOT NULL DEFAULT 'huset',
    has_epl     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Entity → room mapping
CREATE TABLE IF NOT EXISTS entity_map (
    entity_id   TEXT PRIMARY KEY,
    room_id     TEXT NOT NULL REFERENCES rooms(room_id),
    role        TEXT NOT NULL DEFAULT 'sensor',
    meta        JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_entity_map_room ON entity_map(room_id);

-- Sensor data (partitioned by month on ts)
CREATE TABLE IF NOT EXISTS sensor_data (
    ts          TIMESTAMPTZ NOT NULL,
    entity_id   TEXT NOT NULL,
    state       TEXT,
    value       DOUBLE PRECISION,
    attrs       JSONB,
    room_id     TEXT
) PARTITION BY RANGE (ts);

-- Events (partitioned by week on ts)
CREATE TABLE IF NOT EXISTS events (
    ts          TIMESTAMPTZ NOT NULL,
    event_type  TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'ha',
    data        JSONB NOT NULL DEFAULT '{}',
    room_id     TEXT
) PARTITION BY RANGE (ts);
"""

# ── Seed data ──────────────────────────────────────────────────────
ROOMS_SEED = """
INSERT INTO rooms (room_id, name_da, name_en, floor, zone, has_epl)
VALUES
    ('alrum',             'Alrum',              'Living Room',       'ground', 'huset', TRUE),
    ('koekken',           'K\u00f8kken',       'Kitchen',           'ground', 'huset', TRUE),
    ('gang',              'Gang',               'Hallway',           'ground', 'huset', TRUE),
    ('badevaerelse',      'Badev\u00e6relse',   'Bathroom',          'ground', 'huset', TRUE),
    ('udestue',           'Udestue',            'Conservatory',      'ground', 'huset', TRUE),
    ('sovevaerelse',      'Sovev\u00e6relse',   'Bedroom',           'ground', 'huset', FALSE),
    ('darwins_vaerelse',  'Darwins V\u00e6relse', 'Darwins Room',  'ground', 'huset', TRUE)
ON CONFLICT (room_id) DO NOTHING;
"""


def _monthly_partition_sql(table: str, year: int, month: int) -> str:
    """Generate DDL for a monthly partition with BRIN index."""
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)
    name = f"{table}_{start.strftime('%Y_%m')}"
    return f"""
CREATE TABLE IF NOT EXISTS {name}
    PARTITION OF {table}
    FOR VALUES FROM ('{start.strftime('%Y-%m-%d')}') TO ('{end.strftime('%Y-%m-%d')}');
CREATE INDEX IF NOT EXISTS idx_{name}_ts ON {name} USING BRIN (ts);
"""


def _weekly_partition_sql(table: str, week_start: datetime) -> str:
    """Generate DDL for a weekly partition with BRIN index."""
    week_end = week_start + timedelta(days=7)
    name = f"{table}_{week_start.strftime('%Y_w%W')}"
    return f"""
CREATE TABLE IF NOT EXISTS {name}
    PARTITION OF {table}
    FOR VALUES FROM ('{week_start.strftime('%Y-%m-%d')}') TO ('{week_end.strftime('%Y-%m-%d')}');
CREATE INDEX IF NOT EXISTS idx_{name}_ts ON {name} USING BRIN (ts);
"""


async def init_schema(db: "Database") -> None:
    """Create core tables, seed rooms, and ensure partitions exist."""
    logger.info("Initializing database schema...")

    # Core tables
    await db.execute(SCHEMA_SQL)
    logger.info("Core tables created")

    # Seed rooms
    await db.execute(ROOMS_SEED)
    logger.info("Rooms seeded")

    # Create partitions for current + next 2 months
    await ensure_partitions(db, months_ahead=2)
    await ensure_event_partitions(db, weeks_ahead=4)

    logger.info("Schema initialization complete")


async def ensure_partitions(db: "Database", months_ahead: int = 2) -> None:
    """Create monthly sensor_data partitions for current + future months."""
    now = datetime.utcnow()
    for offset in range(months_ahead + 1):
        month = now.month + offset
        year = now.year
        while month > 12:
            month -= 12
            year += 1
        sql = _monthly_partition_sql("sensor_data", year, month)
        try:
            await db.execute(sql)
            logger.debug("Ensured partition sensor_data_%d_%02d", year, month)
        except Exception as exc:
            # Partition may already exist — that is fine
            logger.debug("Partition sensor_data_%d_%02d: %s", year, month, exc)


async def ensure_event_partitions(db: "Database", weeks_ahead: int = 4) -> None:
    """Create weekly event partitions for current + future weeks."""
    now = datetime.utcnow()
    # Start from Monday of current week
    monday = now - timedelta(days=now.weekday())
    monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)

    for offset in range(weeks_ahead + 1):
        week_start = monday + timedelta(weeks=offset)
        sql = _weekly_partition_sql("events", week_start)
        try:
            await db.execute(sql)
            logger.debug("Ensured partition events_%s", week_start.strftime('%Y_w%W'))
        except Exception as exc:
            logger.debug("Partition events_%s: %s", week_start.strftime('%Y_w%W'), exc)


async def drop_old_partitions(db: "Database", sensor_days: int = 90, event_days: int = 365) -> None:
    """Drop partitions older than retention thresholds."""
    sensor_cutoff = datetime.utcnow() - timedelta(days=sensor_days)
    event_cutoff = datetime.utcnow() - timedelta(days=event_days)

    # Find and drop old sensor_data partitions
    rows = await db.fetch(
        """
        SELECT schemaname, tablename FROM pg_tables
        WHERE tablename LIKE 'sensor_data_%'
        ORDER BY tablename
        """
    )
    for row in rows:
        table = row["tablename"]
        # Extract year_month from table name: sensor_data_2026_03
        parts = table.replace("sensor_data_", "").split("_")
        if len(parts) == 2:
            try:
                part_date = datetime(int(parts[0]), int(parts[1]), 1)
                if part_date < sensor_cutoff.replace(day=1):
                    await db.execute(f"DROP TABLE IF EXISTS {table}")
                    logger.info("Dropped old partition: %s", table)
            except (ValueError, IndexError):
                pass

    # Find and drop old event partitions
    rows = await db.fetch(
        """
        SELECT schemaname, tablename FROM pg_tables
        WHERE tablename LIKE 'events_%'
        ORDER BY tablename
        """
    )
    for row in rows:
        table = row["tablename"]
        parts = table.replace("events_", "").split("_w")
        if len(parts) == 2:
            try:
                year = int(parts[0])
                week = int(parts[1])
                part_date = datetime.strptime(f"{year}-W{week:02d}-1", "%Y-W%W-%w")
                if part_date < event_cutoff:
                    await db.execute(f"DROP TABLE IF EXISTS {table}")
                    logger.info("Dropped old partition: %s", table)
            except (ValueError, IndexError):
                pass
