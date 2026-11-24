"""Standard-library HTTP API and static explanation page."""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.data import SEED_LEDGER, get_scenario, scenario_summaries  # noqa: E402
from app.fairness import envy_explanation  # noqa: E402
from app.ledger import AcceptanceLedger, CommitmentConflict  # noqa: E402
from app.solver import (  # noqa: E402
    compare_capacity_and_commitments,
    enumerate_all_assignments,
    solve,
)

WEB_ROOT = ROOT / "web"
DEFAULT_LEDGER = Path(os.environ.get("ALLOC_LEDGER", ROOT / "ledger" / "acceptance-ledger.json"))

_ledger_was_absent = not DEFAULT_LEDGER.exists()
LEDGER = AcceptanceLedger(DEFAULT_LEDGER)
if _ledger_was_absent:
    LEDGER.reset_to_seed()


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Object of type {type(value)!r} is not JSON serializable")


class Handler(BaseHTTPRequestHandler):
    server_version = "FairAllocation/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        # Keep test/server output concise; errors still surface via status codes.
        if os.environ.get("ALLOC_VERBOSE_HTTP"):
            super().log_message(fmt, *args)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=_json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, relative: str) -> None:
        candidate = (WEB_ROOT / relative).resolve()
        if WEB_ROOT.resolve() not in candidate.parents and candidate != WEB_ROOT.resolve():
            self.send_error(403)
            return
        if not candidate.is_file():
            self.send_error(404)
            return
        content_types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
            ".json": "application/json; charset=utf-8",
        }
        body = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_types.get(candidate.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("request body must be a JSON object")
        return data

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            if path == "/api/health":
                self._send_json({"ok": True})
            elif path == "/api/scenarios":
                self._send_json({"scenarios": scenario_summaries()})
            elif path == "/api/scenario":
                sid = query.get("id", ["studio"])[0]
                scenario = get_scenario(sid)
                self._send_json({"scenario": scenario, "ledger": LEDGER.records(sid)})
            elif path == "/api/ledger":
                sid = query.get("scenario", ["studio"])[0]
                self._send_json(
                    {"scenario": sid, "records": LEDGER.records(sid), "active": LEDGER.active_map(sid)}
                )
            elif path == "/api/compare":
                sid = query.get("scenario", ["studio"])[0]
                overrides = None
                if "capacities" in query:
                    overrides = json.loads(query["capacities"][0])
                scenario = get_scenario(sid)
                acceptances = LEDGER.active_map(sid)
                self._send_json(
                    compare_capacity_and_commitments(scenario, acceptances, overrides)
                    | {"scenario": scenario, "ledger_records": LEDGER.records(sid)}
                )
            elif path == "/api/enumerate":
                sid = query.get("scenario", ["micro"])[0]
                scenario = get_scenario(sid)
                result = enumerate_all_assignments(scenario)
                self._send_json(result)
            elif path == "/api/envy":
                sid = query["scenario"][0]
                observer = query["observer"][0]
                target = query["target"][0]
                assignment = json.loads(query["assignment"][0])
                scenario = get_scenario(sid)
                self._send_json(envy_explanation(scenario, assignment, observer, target))
            elif path == "/" or path == "/index.html":
                self._send_static("index.html")
            elif path.startswith("/"):
                self._send_static(path.lstrip("/"))
            else:
                self.send_error(404)
        except KeyError as exc:
            self._send_json({"error": str(exc)}, status=404)
        except (ValueError, RuntimeError) as exc:
            self._send_json({"error": str(exc)}, status=400)
        except Exception as exc:  # pragma: no cover - HTTP boundary
            self._send_json({"error": f"internal error: {exc}"}, status=500)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            body = self._read_json()
            if path == "/api/solve":
                sid = body.get("scenario", "studio")
                scenario = get_scenario(sid)
                acceptances = body.get("acceptances")
                if acceptances is None:
                    acceptances = LEDGER.active_map(sid) if body.get("use_ledger", True) else {}
                result = solve(
                    scenario,
                    objective=body.get("objective", "burden"),
                    acceptances=acceptances,
                    capacity_overrides=body.get("capacity_overrides"),
                )
                self._send_json(result)
            elif path == "/api/compare":
                sid = body.get("scenario", "studio")
                scenario = get_scenario(sid)
                acceptances = body.get("acceptances")
                if acceptances is None:
                    acceptances = LEDGER.active_map(sid)
                result = compare_capacity_and_commitments(
                    scenario, acceptances, body.get("capacity_overrides")
                )
                result["scenario"] = scenario
                result["ledger_records"] = LEDGER.records(sid)
                self._send_json(result)
            elif path == "/api/acceptances":
                sid = body["scenario"]
                pid = body["package_id"]
                mid = body["member_id"]
                scenario = get_scenario(sid)
                package_ids = {p["id"] for p in scenario["packages"]}
                member_ids = {m["id"] for m in scenario["members"]}
                if pid not in package_ids:
                    raise KeyError(f"unknown package {pid}")
                if mid not in member_ids:
                    raise KeyError(f"unknown member {mid}")
                try:
                    record = LEDGER.accept(
                        sid,
                        pid,
                        mid,
                        source=body.get("source", "web"),
                        note=body.get("note", ""),
                        supersede=bool(body.get("supersede", False)),
                    )
                except CommitmentConflict as exc:
                    self._send_json(
                        {"error": str(exc), "code": "commitment_already_exists"},
                        status=409,
                    )
                    return
                status = 200 if record.get("idempotent") else 201
                self._send_json(
                    {
                        "record": record,
                        "active": LEDGER.active_map(sid),
                        "records": LEDGER.records(sid),
                    },
                    status=status,
                )
            elif path == "/api/ledger/clear":
                sid = body.get("scenario")
                removed = LEDGER.clear_scenario(sid) if sid else 0
                self._send_json({"removed": removed, "records": LEDGER.records(sid or "")})
            elif path == "/api/ledger/reset":
                sid = body.get("scenario")
                if sid is not None:
                    get_scenario(sid)
                count = LEDGER.reset_to_seed(sid)
                self._send_json({"records_written": count, "records": LEDGER.records(sid) if sid else LEDGER.records()})
            else:
                self.send_error(404)
        except KeyError as exc:
            self._send_json({"error": str(exc)}, status=404)
        except (ValueError, RuntimeError) as exc:
            self._send_json({"error": str(exc)}, status=400)
        except Exception as exc:  # pragma: no cover
            self._send_json({"error": f"internal error: {exc}"}, status=500)


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Fair allocation workbench running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
