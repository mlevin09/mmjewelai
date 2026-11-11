"""A deterministic loopback HTTP endpoint, never the installed model."""

import copy
import json
import threading
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from native_llm_bench.contracts import Config, load

FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.fixture
def corpus():
    return copy.deepcopy(load(FIXTURES / "synthetic.runtime.json"))


@pytest.fixture
def manifest():
    return load(FIXTURES / "synthetic.model.json")


@pytest.fixture
def endpoint():
    state = SimpleNamespace(requests=[], actions=[], response_ids=[], raw=[], port=None)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state.requests.append({"path": self.path, "body": body})
            index = len(state.requests)
            action = state.actions.pop(0) if state.actions else {}
            if action.get("delay"):
                time.sleep(action["delay"])
            response = {
                "id": f"fake-{index}",
                "model": "synthetic-local-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "actual reply: " + body["messages"][-1]["content"] + " \n",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
            }
            if state.response_ids:
                response["id"] = state.response_ids.pop(0)
            if "response" in action:
                response = action["response"]
            raw = action.get("raw", json.dumps(response, ensure_ascii=False).encode())
            state.raw.append(raw)
            self.send_response(action.get("http", 200))
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw) + action.get("missing_bytes", 0)))
            self.end_headers()
            try:
                self.wfile.write(raw)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            if action.get("missing_bytes"):
                self.close_connection = True

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.config = replace(
        Config(),
        endpoint=f"http://127.0.0.1:{state.port}",
        model="synthetic-local-model",
        max_attempts=2,
        timeout_seconds=1,
    )
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
