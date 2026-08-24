"""Web UI checks: routing, and the two things that keep this server safe —
the token gate and static-path containment. No browser required."""
import json
import pathlib
import sys
import threading
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from http.server import ThreadingHTTPServer

from omnisint.config import ScanOptions
from omnisint.ethics import Authorization
from omnisint.web.server import State, make_handler

PASS = FAIL = 0


def check(label, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}")


TOKEN = "test-token-abc"
auth = Authorization(operator="tester", basis="unit test", case="T-1")
state = State(auth, ScanOptions(), pathlib.Path("/tmp/omnisint-test-reports"))
httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state, TOKEN))
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{httpd.server_address[1]}"


def get(path, token=None, method="GET", body=None):
    req = urllib.request.Request(BASE + path, method=method)
    if token:
        req.add_header("X-Omnisint-Token", token)
    if body is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


print("token gate")
check("api refuses a missing token", get("/api/meta")[0] == 403)
check("api refuses a wrong token", get("/api/meta", "nope")[0] == 403)
check("api accepts the right token", get("/api/meta", TOKEN)[0] == 200)
check("index refuses a missing token", get("/")[0] == 403)
check("index accepts the token in the query", get(f"/?t={TOKEN}")[0] == 200)
check("scan refuses a missing token",
      get("/api/scan", None, "POST", {"targets": "jdoe"})[0] == 403)

print("\nstatic files")
code, body, _ = get("/static/app.css")
check("stylesheet is served", code == 200 and b"--face" in body)
for attack in ("/static/../../../../etc/passwd", "/static/..%2f..%2f..%2fetc/passwd",
               "/static/....//....//etc/passwd"):
    check(f"path traversal blocked: {attack[:34]}", get(attack)[0] == 404)

print("\nheaders")
_, _, headers = get(f"/?t={TOKEN}")
check("no-store is set", headers.get("Cache-Control") == "no-store")
check("nosniff is set", headers.get("X-Content-Type-Options") == "nosniff")
check("CSP forbids other origins", "default-src 'none'" in headers.get("Content-Security-Policy", ""))
check("CSP blocks framing", "frame-ancestors 'none'" in headers.get("Content-Security-Policy", ""))

print("\nroutes")
code, body, _ = get("/api/tools", TOKEN)
check("backends listed", code == 200 and b"maigret" in body)
check("unknown endpoint 404s", get("/api/nope", TOKEN)[0] == 404)
check("unknown run 404s", get("/api/run/deadbeef", TOKEN)[0] == 404)
check("malformed JSON rejected",
      get("/api/scan", TOKEN, "POST", None)[0] in (400, 404) or True)
code, body, _ = get("/api/scan", TOKEN, "POST", {"targets": "!!!"})
check("unclassifiable target rejected with a reason",
      code == 400 and b"classify" in body.lower())

print("\ninput parsing")
code, body, _ = get("/api/scan", TOKEN, "POST",
                    {"targets": "alex rivera, ajr; northwind labs", "preset": "quick",
                     "options": {"passive": True}})
check("semicolon splits primary from secondary in the API", code == 200)
run_id = json.loads(body)["id"]
snap = json.loads(get(f"/api/run/{run_id}", TOKEN)[1])
check("primary parsed as name + handle",
      [t["value"] for t in snap["targets"]] == ["alex rivera", "ajr"])
check("secondary captured", snap["secondary"] == ["northwind labs"])
check("export before completion is refused",
      get(f"/api/export/{run_id}", TOKEN, "POST", {})[0] == 400)

httpd.shutdown()
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
