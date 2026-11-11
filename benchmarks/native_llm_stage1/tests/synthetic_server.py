"""Manual CLI demo ONLY: deterministic acknowledgments, not a language model."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    sequence = 0

    def log_message(self, *_):
        pass

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Handler.sequence += 1
        body = json.dumps(
            {
                "id": f"synthetic-demo-{Handler.sequence}",
                "model": "synthetic-local-model",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "SYNTHETIC acknowledgment; messages="
                            + str(len(request["messages"])),
                        },
                        "finish_reason": "stop",
                    }
                ],
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", type=int, default=8080)
    args = p.parse_args()
    server = HTTPServer(("127.0.0.1", args.port), Handler)
    print("SYNTHETIC fake endpoint only; Ctrl-C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
