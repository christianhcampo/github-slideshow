"""Guardado del dataset final: local (JSON/CSV) o Apify Dataset (push_data)."""
from __future__ import annotations

import csv
import json
import os
from typing import Any, Dict, List


def save_json(records: List[Dict[str, Any]], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2, default=str)


def save_csv(records: List[Dict[str, Any]], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if not records:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("")
        return

    fieldnames: List[str] = []
    for record in records:
        for key in record.keys():
            if key not in fieldnames:
                fieldnames.append(key)

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            row = {}
            for key in fieldnames:
                value = record.get(key)
                if isinstance(value, (list, dict)):
                    value = json.dumps(value, ensure_ascii=False)
                row[key] = value
            writer.writerow(row)


async def push_to_apify_dataset(records: List[Dict[str, Any]]) -> None:
    """Empuja los registros al Dataset por defecto del Actor (solo dentro de Apify)."""
    from apify import Actor

    for record in records:
        await Actor.push_data(record)
