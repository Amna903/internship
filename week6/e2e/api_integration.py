"""Week 6 Step 5: API integration checks against the running containers (CI Docker job; works locally too).

Standard library only. Reads the seeded passwords from backend/.env and never prints them.
Usage:  python3 e2e/api_integration.py <frontend_base> <backend_base>
"""

import http.cookiejar
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

FRONT, BACK = sys.argv[1].rstrip("/"), sys.argv[2].rstrip("/")
ENV = dict(line.split("=", 1) for line in (Path(__file__).resolve().parents[1] / "backend/.env").read_text().splitlines()
           if "=" in line and not line.lstrip().startswith("#"))
PREDICT = {"lead_time_days": 14, "appointment_weekday": "tuesday", "appointment_hour": 10, "age_band": "35-44",
           "visit_type": "in_person", "booking_channel": "web", "reminder_sent": True, "prior_appointments": 4,
           "prior_no_shows": 0, "distance_km": 6.5}
results = []


def check(name, ok):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, flush=True)


class Session:
    """A browser-like client: cookie jar, CSRF header on unsafe methods, JSON in and out."""

    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, method, path, body=None, base=FRONT):
        headers = {"Accept": "application/json"}
        if method != "GET":
            headers["X-CSRFToken"] = next((c.value for c in self.jar if c.name == "csrftoken"), "")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(base + path, method=method, headers=headers,
                                     data=None if body is None else json.dumps(body).encode())
        try:
            with self.opener.open(req, timeout=60) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, None


admin, member = Session(), Session()
status, body = admin.call("GET", "/ready/", base=BACK)
check(f"/ready/ is ready ({status})", status == 200 and body["status"] == "ready")
admin.call("GET", "/api/auth/csrf/")
status, _ = admin.call("POST", "/api/admin/login/", {"email": "admin@example.test", "password": ENV["SEED_ADMIN_PASSWORD"]})
check(f"admin signs in through the frontend proxy with CSRF ({status})", status == 200)
status, body = admin.call("POST", "/api/v1/predict/", PREDICT)
check(f"prediction ({status})", status == 200 and 0 <= body["prediction"]["no_show_probability"] <= 1)
status, body = admin.call("POST", "/api/v1/predict/", {**PREDICT, "appointment_hour": 99})
check(f"invalid input rejected ({status})", status == 400)
status, body = admin.call("GET", "/api/v1/clusters/")
check(f"clusters ({status})", status == 200 and "real" in body)
status, body = admin.call("POST", "/api/v1/assistant/ask/", {"question": "How many times can I reschedule?"})
check(f"assistant responds calmly ({status}, {body and body.get('status')})",
      status == 200 and body["status"] in ("answered", "insufficient_information"))
member.call("GET", "/api/auth/csrf/")
status, _ = member.call("POST", "/api/auth/user/login/", {"email": "amina.rahman@example.test",
                                                          "password": ENV["SEED_USER_PASSWORD"]})
check(f"member signs in ({status})", status == 200)
status, _ = member.call("POST", "/api/v1/predict/", PREDICT)
check(f"member refused the admin prediction API ({status})", status in (401, 403))
status, _ = member.call("POST", "/api/v1/agent/run/", {"message": "Book a slot"})
check(f"member refused the agent ({status})", status in (401, 403))
status, _ = Session().call("GET", "/api/profiles/me/")
check(f"anonymous refused a profile ({status})", status in (401, 403))

print(f"\n{sum(results)}/{len(results)} API integration checks passed")
sys.exit(0 if all(results) else 1)
