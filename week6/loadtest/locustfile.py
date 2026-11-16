"""Week 6 Step 8: a small, fixed synthetic workload on two core endpoints (see docs/REQUIREMENTS.md, Step 8 rules).

Signs in once per simulated user as the seeded admin; the password is read from backend/.env, never printed.
"""

import random
from pathlib import Path

from locust import HttpUser, between, task

ENV = dict(
    line.split("=", 1)
    for line in (Path(__file__).resolve().parents[1] / "backend/.env").read_text().splitlines()
    if "=" in line and not line.lstrip().startswith("#")
)
APPOINTMENT = {
    "lead_time_days": 14,
    "appointment_weekday": "tuesday",
    "appointment_hour": 10,
    "age_band": "35-44",
    "visit_type": "in_person",
    "booking_channel": "web",
    "reminder_sent": True,
    "prior_appointments": 4,
    "prior_no_shows": 0,
    "distance_km": 6.5,
}
random.seed(42)


class Admin(HttpUser):
    wait_time = between(0.1, 0.5)

    def on_start(self):
        self.client.get("/api/auth/csrf/", name="setup: csrf")
        self.csrf = self.client.cookies.get("csrftoken")
        response = self.client.post(
            "/api/admin/login/",
            json={"email": "admin@example.test", "password": ENV["SEED_ADMIN_PASSWORD"]},
            headers={"X-CSRFToken": self.csrf, "Referer": self.host + "/"},
            name="setup: login",
        )
        response.raise_for_status()
        self.csrf = self.client.cookies.get("csrftoken")

    @task(3)
    def predict(self):
        self.client.post(
            "/api/v1/predict/",
            json=APPOINTMENT,
            headers={"X-CSRFToken": self.csrf, "Referer": self.host + "/"},
            name="POST /api/v1/predict/",
        )

    @task(1)
    def clusters(self):
        self.client.get("/api/v1/clusters/", name="GET /api/v1/clusters/")
