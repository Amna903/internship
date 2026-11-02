"""Development settings (Week 6 Step 2): DEBUG on, plain HTTP on localhost. Never use in production."""

import os

for key, value in {"DJANGO_DEBUG": "true", "COOKIE_SECURE": "false"}.items():
    os.environ.setdefault(key, value)

from .settings import *  # noqa: E402,F401,F403
