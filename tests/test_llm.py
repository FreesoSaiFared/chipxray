import json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from chipxray.llm import LLM, ScriptedLLM

REPLY = {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
    {"id": "t1", "type": "function", "function": {"name": "candidates", "arguments": "{\"top\": 3}"}}]}}],
    "usage": {"prompt_tokens": 11, "completion_tokens": 7}}


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        H.last = (self.path, self.headers.get("Authorization"), body)
        out = json.dumps(REPLY).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)

    def log_message(self, *a):
        pass


def test_llm_posts_openai_format_and_parses_tool_calls():
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    llm = LLM(base_url=f"http://127.0.0.1:{srv.server_port}/v1", api_key="k", model="m")
    msg = llm.chat([{"role": "user", "content": "hi"}], tools=[{"type": "function", "function": {"name": "candidates"}}])
    srv.shutdown()
    path, auth, body = H.last
    assert path == "/v1/chat/completions" and auth == "Bearer k" and body["model"] == "m" and body["tools"]
    assert msg["tool_calls"][0]["function"]["name"] == "candidates"
    assert llm.usage == {"prompt_tokens": 11, "completion_tokens": 7, "calls": 1}


def test_scripted_llm_replays_in_order():
    s = ScriptedLLM([{"role": "assistant", "content": "a"}, {"role": "assistant", "content": "b"}])
    assert s.chat([{"role": "user", "content": "1"}])["content"] == "a"
    assert s.chat([{"role": "user", "content": "2"}])["content"] == "b"
    assert len(s.seen) == 2 and s.usage["calls"] == 2


if __name__ == "__main__":
    test_llm_posts_openai_format_and_parses_tool_calls(); test_scripted_llm_replays_in_order(); print("ok")
