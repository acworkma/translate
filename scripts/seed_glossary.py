"""Seed the Cosmos `glossary` container from a TSV.

Input file format (TSV, header row required):
  source<TAB>language<TAB>target<TAB>notes
  Tylenol<TAB>es<TAB>Tylenol<TAB>brand name — keep verbatim
  ...

Usage:
  COSMOS_ENDPOINT=... COSMOS_DATABASE=translate \\
    python scripts/seed_glossary.py data/glossary_seed.tsv
"""
from __future__ import annotations

import csv
import os
import sys

from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential


def main(path: str) -> int:
    endpoint = os.environ["COSMOS_ENDPOINT"]
    database = os.environ.get("COSMOS_DATABASE", "translate")
    container = CosmosClient(endpoint, credential=DefaultAzureCredential()) \
        .get_database_client(database).get_container_client("glossary")

    count = 0
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            source = (row.get("source") or "").strip()
            language = (row.get("language") or "").strip()
            target = (row.get("target") or "").strip()
            notes = (row.get("notes") or "").strip()
            if not source or not language or not target:
                continue
            item = {
                "id": source.lower(),
                "source": source,
                "language": language,
                "target": target,
                "notes": notes,
            }
            container.upsert_item(item)
            count += 1
    print(f"seeded {count} glossary entries")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: seed_glossary.py <path-to-tsv>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
