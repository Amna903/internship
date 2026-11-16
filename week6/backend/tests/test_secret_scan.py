"""Week 6 Step 10 (S2): the git-tracked files hold no secrets: no .env file, no private keys, nothing shaped like
a real API key or token, and (when a local backend/.env exists) none of its secret values."""

import re
import subprocess
from pathlib import Path

import pytest

WEEK = Path(__file__).resolve().parents[2]
REPO = WEEK.parent
PATTERNS = {
    "private key": re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "AWS key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9]{36}"),
    "OpenAI/Anthropic-style key": re.compile(r"sk-(ant-)?[A-Za-z0-9_-]{32,}"),
    "Slack token": re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
}
SECRET_NAMES = ("SECRET_KEY", "PASSWORD", "TOKEN")


def tracked():
    try:
        out = subprocess.run(
            ["git", "ls-files", "week6", ".github"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return [REPO / f for f in out.splitlines()]


def text_of(path):
    try:
        return path.read_text()
    except (UnicodeDecodeError, OSError):
        return ""


def test_no_env_files_or_keys_are_tracked():
    files = tracked()
    assert files
    assert not [f for f in files if f.name == ".env" or (f.name.startswith(".env.") and f.name != ".env.example")]
    assert not [f for f in files if f.suffix in (".pem", ".key", ".p12", ".sqlite3", ".dump")]


def test_no_key_shaped_strings_are_tracked():
    hits = [
        f"{f.relative_to(REPO)}: {name}" for f in tracked() for name, rx in PATTERNS.items() if rx.search(text_of(f))
    ]
    assert hits == []


def test_local_secret_values_never_appear_in_tracked_files():
    env = WEEK / "backend" / ".env"
    if not env.is_file():
        pytest.skip("no local backend/.env (CI)")
    values = [
        v.strip()
        for k, _, v in (line.partition("=") for line in env.read_text().splitlines())
        if any(n in k for n in SECRET_NAMES) and len(v.strip()) >= 12
    ]
    assert values
    leaked = [str(f.relative_to(REPO)) for f in tracked() for v in values if v in text_of(f)]
    assert leaked == []  # file names only: the values themselves are never printed
