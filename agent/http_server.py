"""HTTP Tool Server — 最小 HTTP API，暴露 AgentToolRegistry

启动: python -m agent.http_server --port 8765
调用: curl -X POST http://localhost:8765/tools/call -d '{"name":"answer_question","params":{"question":"hello"}}'
"""
import json
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from . import AgentToolRegistry


class ToolHandler(BaseHTTPRequestHandler):
    """处理 /tools/* 路由"""

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/tools/list":
            tools = AgentToolRegistry.list_tools()
            self._send_json({"ok": True, "data": tools})
        elif self.path == "/health":
            self._send_json({"ok": True, "data": {"status": "ok"}})
        else:
            self._send_json(
                {"ok": False, "error": {"code": "NOT_FOUND", "message": self.path}},
                status=404,
            )

    def do_POST(self):
        if self.path == "/tools/call":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length)
                req = json.loads(body)

                name = req.get("name", "")
                params = req.get("params", {})

                result = AgentToolRegistry.call(name, params)
                self._send_json(
                    result.to_dict(),
                    status=200 if result.ok else 400,
                )
            except json.JSONDecodeError:
                self._send_json(
                    {"ok": False, "error": {"code": "INVALID_JSON"}}, status=400)
        else:
            self._send_json(
                {"ok": False, "error": {"code": "NOT_FOUND"}}, status=404)

    def log_message(self, format, *args):
        """Suppress default HTTP logging"""
        pass


def run_server(host: str = "127.0.0.1", port: int = 8765):
    """启动 HTTP Tool Server"""
    server = HTTPServer((host, port), ToolHandler)
    print(f"EDIS Agent HTTP Server: http://{host}:{port}")
    print(f"  Tools: GET  http://{host}:{port}/tools/list")
    print(f"  Call:  POST http://{host}:{port}/tools/call")
    print(f"  Health: GET  http://{host}:{port}/health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    port = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == "--port" else 8765
    run_server(port=port)
