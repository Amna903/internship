"""The Celery app (Week 5 Step 10). Settings come from Django's, prefixed CELERY_. Worker:
`celery -A config worker -l info --pool=solo` (see the README's "Run and test")."""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("healthprofile")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks(["assistant"], related_name="jobs")
