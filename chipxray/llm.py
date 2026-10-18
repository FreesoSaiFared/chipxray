"""Minimal client for any OpenAI-compatible chat endpoint with tool calling. Stdlib only."""
import json, os, time, urllib.error, urllib.request


class LLM:
    def __init__(self, base_url=None, api_key=None, model=None, timeout=180):
        self.base_url = (base_url or os.environ["CHIPXRAY_LLM_BASE_URL"]).rstrip("/")
        self.api_key = api_key or os.environ.get("CHIPXRAY_LLM_API_KEY", "")
        self.model = model or os.environ["CHIPXRAY_LLM_MODEL"]
        self.timeout = timeout
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}

    def chat(self, messages, tools=None):
        body = {"model": self.model, "messages": messages, "temperature": 0}
        if tools:
            body["tools"] = tools
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {self.api_key}"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    data = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 502, 503) or attempt == 3:
                    raise RuntimeError(f"LLM HTTP {e.code}: {e.read()[:500]!r}") from e
                time.sleep(2 ** attempt * 5)  # rate limits on free tiers
        u = data.get("usage") or {}
        self.usage["prompt_tokens"] += u.get("prompt_tokens", 0)
        self.usage["completion_tokens"] += u.get("completion_tokens", 0)
        self.usage["calls"] += 1
        return data["choices"][0]["message"]


class ScriptedLLM:
    """Replays fixed assistant messages. For tests: no network, deterministic."""
    model = "scripted"

    def __init__(self, replies):
        self.replies, self.seen = list(replies), []
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}

    def chat(self, messages, tools=None):
        self.seen.append(list(messages))
        self.usage["calls"] += 1
        return self.replies.pop(0)
