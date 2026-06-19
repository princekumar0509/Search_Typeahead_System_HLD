"""Generate a synthetic dataset of 100,000+ search queries.

Produces a CSV with two columns: ``query,count``. Counts follow a Zipf-like
distribution (a few very popular head queries, a long tail of rare ones) which
mimics real search traffic and makes the popularity sort / trending features
meaningful.

Usage:
    python -m scripts.generate_dataset --out data/queries.csv --rows 120000
"""
from __future__ import annotations

import argparse
import csv
import itertools
import random

# Seed corpora combined combinatorially to yield a large, realistic vocabulary.
HEAD_TERMS = [
    "iphone", "java", "python", "react", "docker", "kubernetes", "samsung",
    "macbook", "airpods", "playstation", "xbox", "nintendo", "tesla", "nike",
    "adidas", "amazon", "netflix", "spotify", "youtube", "github", "openai",
    "chatgpt", "bitcoin", "ethereum", "iphone 15", "iphone 16", "galaxy s24",
    "system design", "leetcode", "fastapi", "postgres", "redis", "kafka",
    "aws", "azure", "golang", "rust", "typescript", "tailwind", "vite",
]

MODIFIERS = [
    "tutorial", "review", "price", "near me", "online", "for beginners",
    "vs", "best", "cheap", "2025", "deals", "specs", "comparison", "guide",
    "download", "free", "course", "interview questions", "examples", "setup",
    "charger", "case", "pro max", "ultra", "mini", "plus", "lite",
    "documentation", "cheatsheet", "roadmap", "jobs", "salary",
]

SUFFIX_WORDS = [
    "reddit", "amazon", "india", "usa", "uk", "2024", "alternative",
    "tips", "tricks", "explained", "simple", "advanced", "pdf",
]


def _build_vocabulary() -> list[str]:
    """Combine corpora into a large set of unique, realistic queries."""
    queries: set[str] = set()

    # Single head terms.
    queries.update(HEAD_TERMS)

    # head + modifier
    for head, mod in itertools.product(HEAD_TERMS, MODIFIERS):
        queries.add(f"{head} {mod}")

    # head + modifier + suffix
    for head, mod, suf in itertools.product(HEAD_TERMS, MODIFIERS, SUFFIX_WORDS):
        queries.add(f"{head} {mod} {suf}")

    return sorted(queries)


def generate(out_path: str, target_rows: int, seed: int = 42) -> int:
    """Write ``target_rows`` ``query,count`` rows to ``out_path``. Returns count."""
    rng = random.Random(seed)
    vocabulary = _build_vocabulary()

    if len(vocabulary) < target_rows:
        # Pad with numbered variants so we always reach the target row count.
        base = list(vocabulary)
        i = 0
        while len(vocabulary) < target_rows:
            term = base[i % len(base)]
            vocabulary.append(f"{term} {i // len(base) + 1}")
            i += 1

    rng.shuffle(vocabulary)
    rows = vocabulary[:target_rows]

    written = 0
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["query", "count"])
        for idx, query in enumerate(rows):
            # Zipf-ish popularity: rank-based base with random jitter. Shorter /
            # earlier queries get higher counts to create clear head queries.
            rank = idx + 1
            base_count = int(1_000_000 / rank)
            count = max(1, base_count + rng.randint(-base_count // 4 or 1, base_count // 4 or 1))
            writer.writerow([query, count])
            written += 1

    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a synthetic search-query dataset.")
    parser.add_argument("--out", default="data/queries.csv", help="Output CSV path")
    parser.add_argument("--rows", type=int, default=120_000, help="Number of rows to generate")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for reproducibility")
    args = parser.parse_args()

    import os

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    written = generate(args.out, args.rows, args.seed)
    print(f"Wrote {written:,} rows to {args.out}")


if __name__ == "__main__":
    main()
