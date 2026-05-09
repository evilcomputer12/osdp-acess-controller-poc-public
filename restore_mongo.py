#!/usr/bin/env python3
"""Restore an Extended JSON MongoDB backup created by backup_mongo.py."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bson import json_util
from pymongo import MongoClient


def restore_backup(mongo_uri: str, backup_dir: Path) -> None:
    manifest_path = backup_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.json not found in {backup_dir}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    db_name = manifest["database"]

    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    db = client[db_name]

    for collection_name in manifest["collections"]:
        dump_path = backup_dir / f"{collection_name}.json"
        if not dump_path.exists():
            raise FileNotFoundError(f"Missing collection dump: {dump_path}")

        docs = json_util.loads(dump_path.read_text(encoding="utf-8"))
        db[collection_name].drop()
        if docs:
            db[collection_name].insert_many(docs)


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore MongoDB from an Extended JSON backup")
    parser.add_argument("backup_dir", help="Path to backup directory created by backup_mongo.py")
    parser.add_argument("--mongo-uri", default="mongodb://localhost:27017")
    args = parser.parse_args()

    restore_backup(args.mongo_uri, Path(args.backup_dir))
    print(f"Restored backup from {args.backup_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())