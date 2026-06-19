"""Seed the PostgreSQL database from the generated CSV dataset.

Reads ``query,count`` rows and bulk-inserts them into the ``queries`` table.
Uses efficient batched inserts with ``ON CONFLICT`` so the script is
idempotent (re-running updates counts rather than erroring on duplicates).

If the CSV does not exist it is generated on the fly.

Usage:
    python -m scripts.seed_database --csv data/queries.csv --batch-size 5000
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import random

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import SessionLocal, init_db
from app.models.db_models import Query
from app.utils.logging import configure_logging
from scripts.generate_dataset import generate

configure_logging()
logger = logging.getLogger("seed")


def _ensure_csv(csv_path: str, rows: int) -> None:
    if not os.path.exists(csv_path):
        logger.info("CSV %s not found; generating %d rows", csv_path, rows)
        os.makedirs(os.path.dirname(csv_path) or ".", exist_ok=True)
        generate(csv_path, rows)


def seed(csv_path: str, batch_size: int, rows: int) -> int:
    """Load the CSV into the database in batches. Returns rows inserted."""
    _ensure_csv(csv_path, rows)
    init_db()

    rng = random.Random(7)
    session = SessionLocal()
    total = 0
    batch: list[dict] = []

    def flush(records: list[dict]) -> None:
        if not records:
            return
        stmt = pg_insert(Query).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Query.query],
            set_={
                "count": stmt.excluded.count,
                "recent_count": stmt.excluded.recent_count,
                "last_searched": func.now(),
            },
        )
        session.execute(stmt)
        session.commit()

    try:
        with open(csv_path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                query_text = row["query"].strip().lower()
                if not query_text:
                    continue
                count = int(row["count"])
                # Give a fraction of queries some "recent" activity so the
                # recency-aware trending mode produces a different ranking.
                recent = rng.randint(0, count // 20) if rng.random() < 0.3 else 0
                batch.append(
                    {
                        "query": query_text,
                        "count": count,
                        "recent_count": recent,
                    }
                )
                if len(batch) >= batch_size:
                    flush(batch)
                    total += len(batch)
                    logger.info("Seeded %d rows...", total)
                    batch = []

        flush(batch)
        total += len(batch)
    finally:
        session.close()

    logger.info("Seeding complete: %d rows", total)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the queries table from CSV.")
    parser.add_argument("--csv", default="data/queries.csv", help="Input CSV path")
    parser.add_argument("--batch-size", type=int, default=5000, help="Insert batch size")
    parser.add_argument("--rows", type=int, default=120_000, help="Rows to generate if CSV missing")
    args = parser.parse_args()

    seed(args.csv, args.batch_size, args.rows)


if __name__ == "__main__":
    main()
