from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from livekit_interaction_model_demo.runtime.scenarios import ScenarioName, create_runtime_for_demo, run_scenario

DEMO_DIR = Path(__file__).resolve().parent
EVENTS_PATH = DEMO_DIR / "events.jsonl"


async def _run_cli_scenario(scenario: ScenarioName) -> None:
    runtime = create_runtime_for_demo(events_path=EVENTS_PATH)
    runtime.timeline.reset()
    await run_scenario(runtime, scenario)
    print(f"Scenario {scenario} complete. Timeline: {EVENTS_PATH}")


def _read_events() -> list[dict[str, Any]]:
    items = []
    if EVENTS_PATH.exists():
        for line in EVENTS_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip():
                items.append(json.loads(line))
    return items


class DemoHTTPRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(DEMO_DIR / "frontend"), **kwargs)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self._json({"ok": True, "events_path": str(EVENTS_PATH)})
            return
        if path == "/api/events":
            self._json({"events": _read_events()})
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        prefix = "/api/scenario/"
        if not path.startswith(prefix):
            self.send_error(404)
            return
        scenario = path.removeprefix(prefix)
        if scenario not in {"A", "B", "C", "D"}:
            self.send_error(400, "Unknown scenario")
            return
        runtime = create_runtime_for_demo(events_path=EVENTS_PATH)
        runtime.timeline.reset()
        asyncio.run(run_scenario(runtime, scenario))  # type: ignore[arg-type]
        self._json({"scenario": scenario, "events_path": str(EVENTS_PATH)})

    def _json(self, data: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve_web(host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), DemoHTTPRequestHandler)
    print(f"Browser demo: http://{host}:{port}")
    print(f"Timeline: {EVENTS_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="LiveKit interaction model demo")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scenario_parser = subparsers.add_parser("scenario", help="Run a scripted scenario and write events.jsonl")
    scenario_parser.add_argument("scenario", choices=["A", "B", "C", "D"])

    web_parser = subparsers.add_parser("web", help="Start the browser demo server")
    web_parser.add_argument("--host", default="127.0.0.1")
    web_parser.add_argument("--port", type=int, default=8008)

    args = parser.parse_args()
    if args.command == "scenario":
        asyncio.run(_run_cli_scenario(args.scenario))
    elif args.command == "web":
        serve_web(args.host, args.port)


if __name__ == "__main__":
    main()
