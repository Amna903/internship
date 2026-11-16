import base64
import json
from datetime import timedelta

from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def decode_payload(token: str) -> dict:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def expired_access_token(user) -> str:
    token = AccessToken.for_user(user)
    token.set_exp(from_time=timezone.now() - timedelta(hours=1), lifetime=timedelta(minutes=1))
    return str(token)


def tamper_payload(token: str, **claims) -> str:
    """Change claims but keep the original signature -> must fail verification."""
    header, payload, signature = token.split(".")
    data = decode_payload(token)
    data.update(claims)
    return f"{header}.{b64(json.dumps(data).encode())}.{signature}"


def unsigned_token(**claims) -> str:
    """A classic `alg: none` forgery."""
    header = b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    return f"{header}.{b64(json.dumps(claims).encode())}."
