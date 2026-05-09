#!/usr/bin/env python3
"""Export the local osdp_access MongoDB database as Extended JSON files."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from bson import json_util
from pymongo import MongoClient


def export_database(mongo_uri: str, db_name: str, output_root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = output_root / f"mongodb_{db_name}_{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    db = client[db_name]

    manifest = {
        "database": db_name,
        "mongo_uri": mongo_uri,
        "created_at": datetime.now().isoformat(),
        "collections": {},
    }

    for name in sorted(db.list_collection_names()):
        docs = list(db[name].find())
        with (backup_dir / f"{name}.json").open("w", encoding="utf-8") as handle:
            handle.write(json_util.dumps(docs, indent=2))
        manifest["collections"][name] = len(docs)

    with (backup_dir / "manifest.json").open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)

    return backup_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Back up MongoDB as Extended JSON")
    parser.add_argument("--mongo-uri", default="mongodb://localhost:27017")
    parser.add_argument("--db", default="osdp_access")
    parser.add_argument("--output-dir", default="backups")
    args = parser.parse_args()

    backup_dir = export_database(args.mongo_uri, args.db, Path(args.output_dir))
    print(backup_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())