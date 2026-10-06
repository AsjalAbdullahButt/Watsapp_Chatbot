"""Meta webhook signature verification (X-Hub-Signature-256)."""

import hashlib
import hmac

from app.core.errors import InvalidSignature

_PREFIX = "sha256="


def verify_meta_signature(raw_body: bytes, header_value: str | None, app_secret: str) -> None:
    """Raise InvalidSignature unless the body was signed with the app secret."""
    if not app_secret:
        raise InvalidSignature("META_APP_SECRET is not configured")
    if not header_value or not header_value.startswith(_PREFIX):
        raise InvalidSignature("missing or malformed signature header")
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, header_value[len(_PREFIX):]):
        raise InvalidSignature("signature mismatch")


def sign_body(raw_body: bytes, app_secret: str) -> str:
    """Produce a valid header value. Used by tests and local tooling only."""
    return _PREFIX + hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
