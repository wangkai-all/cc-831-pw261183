"""Append-only acceptance ledger.

A ledger record means a member has accepted a work package.  The active
commitment map is the latest record for each package (acceptance is normally
idempotent); re-optimization must treat those package owners as fixed.  Demo
reset/clear operations are explicit administrative actions.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from .data import SEED_LEDGER


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CommitmentConflict(ValueError):
    """Raised when a normal acceptance would move an existing commitment."""


class AcceptanceLedger:
    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self._lock = RLock()
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._write({"records": []})

    def _read(self) -> dict[str, Any]:
        with self.path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if "records" not in data or not isinstance(data["records"], list):
            raise ValueError("ledger must contain a records list")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, self.path)

    def records(self, scenario: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._read()["records"]
        if scenario is None:
            return rows
        return [r for r in rows if r.get("scenario") == scenario]

    def active_map(self, scenario: str) -> dict[str, str]:
        active: dict[str, str] = {}
        for record in self.records(scenario):
            # Records are append-only and ordered; a newer acceptance for the
            # same package represents the current factual commitment.
            active[record["package_id"]] = record["member_id"]
        return active

    def accept(
        self,
        scenario: str,
        package_id: str,
        member_id: str,
        *,
        source: str = "web",
        note: str = "",
        supersede: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            scenario_records = [r for r in data["records"] if r.get("scenario") == scenario]
            current_owner = None
            current_record = None
            for record in scenario_records:
                if record.get("package_id") == package_id:
                    current_owner = record.get("member_id")
                    current_record = record

            if current_owner == member_id and current_record is not None:
                return {**current_record, "idempotent": True}
            if current_owner is not None and not supersede:
                raise CommitmentConflict(
                    f"{package_id} 已被 {current_owner} 接受；承诺不能通过重新接受而移动。"
                    "请使用显式 supersede 管理操作，或重置演示台账。"
                )

            record = {
                "id": f"acc_{_now().replace('-', '').replace(':', '').replace('+', 'Z')}_{package_id}_{member_id}",
                "scenario": scenario,
                "package_id": package_id,
                "member_id": member_id,
                "accepted_at": _now(),
                "source": source,
                "note": note,
            }
            if current_owner is not None:
                record["supersedes_member_id"] = current_owner
                record["source"] = f"{source}:supersede"
            data["records"].append(record)
            self._write(data)
        return record

    def clear_scenario(self, scenario: str) -> int:
        with self._lock:
            data = self._read()
            before = len(data["records"])
            data["records"] = [r for r in data["records"] if r.get("scenario") != scenario]
            removed = before - len(data["records"])
            self._write(data)
        return removed

    def reset_to_seed(self, scenario: str | None = None) -> int:
        """Reset all scenarios, or one scenario, to the fictional seed ledger."""
        with self._lock:
            data = self._read()
            if scenario is None:
                data["records"] = [dict(r) for rows in SEED_LEDGER.values() for r in rows]
            else:
                data["records"] = [
                    r for r in data["records"] if r.get("scenario") != scenario
                ]
                data["records"].extend(dict(r) for r in SEED_LEDGER.get(scenario, []))
            self._write(data)
            return len(data["records"])
