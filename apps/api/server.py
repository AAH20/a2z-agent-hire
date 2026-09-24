"""HTTP API and local web shell for A2Z Agent Hire."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from packages.oss.outcome_exchange.core import ExchangeDB


ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "apps" / "web" / "index.html"


class Handler(BaseHTTPRequestHandler):
    db: ExchangeDB

    def log_message(self, *_args):
        return

    def send_json(self, status: int, value: object) -> None:
        body = json.dumps(value, indent=2, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self) -> dict:
        size = int(self.headers.get("Content-Length", "0"))
        if size < 0 or size > 1_048_576:
            raise ValueError("request body exceeds local API limit")
        value = json.loads(self.rfile.read(size) if size else b"{}")
        if not isinstance(value, dict):
            raise ValueError("request body must be an object")
        return value

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/":
                body = WEB.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path == "/api/health":
                self.send_json(200, {"ok": True, "version": "0.1.0", "scope": "LOCAL_OSS_REFERENCE"})
            elif path == "/api/jobs":
                self.send_json(200, {"jobs": self.db.jobs()})
            elif path == "/api/opportunities":
                params = parse_qs(parsed.query)
                status = params.get("status", ["ACTIVE"])[0]
                query, location = params.get("q", [""])[0], params.get("location", [""])[0]
                if query or location:
                    if status != "ACTIVE":
                        raise ValueError("search only supports active opportunities")
                    self.send_json(200, {"opportunities": self.db.opportunities.search(query, location),
                                         "retrieval_model": "LOCAL_DETERMINISTIC_TEXT_V1"})
                else:
                    self.send_json(200, {"opportunities": self.db.opportunities.list(None if status == "ALL" else status)})
            elif path == "/api/tracks":
                self.send_json(200, {"tracks": self.db.opportunities.tracks()})
            elif path.startswith("/api/jobs/") and path.endswith("/economics"):
                self.send_json(200, self.db.economics(path.split("/")[3]))
            elif path.startswith("/api/jobs/"):
                self.send_json(200, self.db.job(path.split("/")[3]))
            elif path == "/api/workers":
                self.send_json(200, {"workers": self.db.workers()})
            elif path == "/api/evolution":
                self.send_json(200, {"candidates": self.db.evolutions()})
            else:
                self.send_json(404, {"error": "not found"})
        except KeyError as exc:
            self.send_json(404, {"error": str(exc)})
        except Exception as exc:
            self.send_json(400, {"error": str(exc)})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            data = self.read_body()
            if path == "/api/jobs":
                self.send_json(201, self.db.create_job(data))
            elif path.startswith("/api/opportunities/") and path.endswith("/track"):
                self.send_json(200, self.db.opportunities.track(path.split("/")[3],
                              str(data.get("status", "")), str(data.get("note", "")),
                              data.get("follow_up_at")))
            elif path == "/api/workers":
                self.send_json(201, self.db.create_worker(data))
            elif path == "/api/evolution":
                self.send_json(201, self.db.create_evolution(data))
            elif path.startswith("/api/jobs/") and path.endswith("/applications"):
                self.send_json(201, self.db.apply(path.split("/")[3], data))
            elif path.startswith("/api/jobs/") and path.endswith("/launch"):
                self.send_json(200, self.db.launch(path.split("/")[3]))
            elif path.startswith("/api/jobs/") and path.endswith("/acceptance"):
                self.send_json(200, self.db.accept(path.split("/")[3], str(data.get("decision", "")), str(data.get("reviewer", ""))))
            elif path.startswith("/api/runs/") and path.endswith("/evidence"):
                self.send_json(200, self.db.record_evidence(path.split("/")[3], str(data.get("criterion_id", "")),
                                                             str(data.get("verifier", "")), str(data.get("artifact_sha256", ""))))
            elif path.startswith("/api/applications/") and path.endswith("/decision"):
                application_id = path.split("/")[3]
                row = self.db.db.execute("SELECT job_id FROM applications WHERE id=?", (application_id,)).fetchone()
                if row is None:
                    raise KeyError("application not found")
                self.send_json(200, self.db.decide_application(application_id, str(data.get("status", "")), str(data.get("reviewer", ""))))
            else:
                self.send_json(404, {"error": "not found"})
        except KeyError as exc:
            self.send_json(404, {"error": str(exc)})
        except Exception as exc:
            self.send_json(400, {"error": str(exc)})


def serve(db_path: str, host: str, port: int) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("reference API has no authentication; bind only to loopback")
    db = ExchangeDB(db_path)
    Handler.db = db
    server = HTTPServer((host, port), Handler)
    print(f"A2Z Agent Hire listening at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local A2Z Agent Hire OSS reference app")
    parser.add_argument("--db", default="a2z-agent-hire.db")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    serve(args.db, args.host, args.port)


if __name__ == "__main__":
    main()
