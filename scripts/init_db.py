#!/usr/bin/env python3
"""Initialize a fresh osdp_access MongoDB database by creating indexes and default schedules."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models import get_db, list_schedules


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize the osdp_access MongoDB database")
    parser.add_argument("--mongo-uri", default="mongodb://localhost:27017")
    args = parser.parse_args()

    db = get_db(args.mongo_uri)
    schedules = list_schedules(db)
    print(f"Initialized database with {len(schedules)} schedule(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())