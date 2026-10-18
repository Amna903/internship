#!/usr/bin/env python3
"""Create backend/.env from .env.example with freshly generated secrets.

Never overwrites an existing .env. Demo passwords are printed once, not committed anywhere.
"""

import secrets
from pathlib import Path

root = Path(__file__).resolve().parent.parent
example, target = root / ".env.example", root / ".env"

if target.exists():
    print(".env already exists; leaving it untouched.")
    raise SystemExit(0)

admin_pw = secrets.token_urlsafe(14)
user_pw = secrets.token_urlsafe(14)

text = example.read_text()
text = text.replace("DJANGO_SECRET_KEY=replace-me", f"DJANGO_SECRET_KEY={secrets.token_urlsafe(50)}")
text = text.replace("JWT_SIGNING_KEY=replace-me", f"JWT_SIGNING_KEY={secrets.token_urlsafe(50)}")
text = text.replace("SEED_ADMIN_PASSWORD=", f"SEED_ADMIN_PASSWORD={admin_pw}")
text = text.replace("SEED_USER_PASSWORD=", f"SEED_USER_PASSWORD={user_pw}")
target.write_text(text)
target.chmod(0o600)

print("Created backend/.env with generated secrets.")
print(f"  Demo admin password : {admin_pw}   (admin@example.test)")
print(f"  Demo user password  : {user_pw}   (all seeded users)")
