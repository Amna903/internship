"""Validation of uploaded policy documents. Uploaded text is untrusted: it is checked here, stored as
`pending`, and only an explicit admin approval makes it searchable. Even then it reaches the model only as
quoted data inside a marked passage block, never as instructions.

Checks, in order (the first failure is reported, with a plain message and no file contents):
  1. a file was sent and it is not empty;
  2. size at most MAX_UPLOAD_BYTES;
  3. extension .txt or .md;
  4. content is really text: no known binary signature (PDF, ZIP/Office, PNG, JPEG, GIF, executables)
     whatever the extension says, no NUL bytes, valid UTF-8, almost no control characters;
  5. the file name is reduced to a safe base name.
Duplicate content (same SHA-256) is rejected by the caller.
"""

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath

MAX_UPLOAD_BYTES = 50_000  # a policy is a few kilobytes; anything this large is not one
ALLOWED_EXTENSIONS = {".txt", ".md"}
BINARY_SIGNATURES = {
    b"%PDF": "PDF",
    b"PK\x03\x04": "ZIP or Office file",
    b"\x89PNG": "PNG image",
    b"\xff\xd8\xff": "JPEG image",
    b"GIF8": "GIF image",
    b"MZ": "Windows executable",
    b"\x7fELF": "executable",
}
MAX_CONTROL_SHARE = 0.01
MAX_NAME_LENGTH = 100


class UploadRejected(ValueError):
    pass


@dataclass(frozen=True)
class ValidUpload:
    filename: str
    content: str
    sha256: str


def safe_filename(name: str) -> str:
    """Base name only (no folders, either slash style), safe characters, bounded length."""
    base = PureWindowsPath(PurePosixPath(name).name).name
    base = unicodedata.normalize("NFKC", base)
    base = re.sub(r"-{2,}", "-", re.sub(r"[^A-Za-z0-9._-]", "-", base)).strip(".-")
    stem, dot, ext = base.rpartition(".")
    if not dot:
        stem, ext = base, ""
    stem = stem.strip(".-")[: MAX_NAME_LENGTH - len(ext) - 1] or "document"
    return f"{stem}.{ext.lower()}" if ext else stem


def validate_upload(name: str | None, data: bytes | None) -> ValidUpload:
    if not name or data is None:
        raise UploadRejected("Choose a file to upload.")
    if not data.strip():
        raise UploadRejected("The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadRejected(f"The file is larger than {MAX_UPLOAD_BYTES // 1000} KB.")
    filename = safe_filename(name)
    if PurePosixPath(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise UploadRejected("Only .txt and .md files can be uploaded.")
    for signature, kind in BINARY_SIGNATURES.items():
        if data.startswith(signature):
            raise UploadRejected(f"The file content is a {kind}, not text, whatever its extension says.")
    if b"\x00" in data:
        raise UploadRejected("The file contains binary data, not text.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise UploadRejected("The file must be UTF-8 text.") from None
    text = text.lstrip("﻿")
    controls = sum(1 for ch in text if unicodedata.category(ch) == "Cc" and ch not in "\n\r\t")
    if controls > MAX_CONTROL_SHARE * len(text):
        raise UploadRejected("The file contains too many control characters to be a text document.")
    return ValidUpload(filename=filename, content=text, sha256=hashlib.sha256(data).hexdigest())
