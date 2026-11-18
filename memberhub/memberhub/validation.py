"""Input validation helpers. All user input is validated before it reaches SQL."""
import re
from datetime import datetime
from urllib.parse import urlparse

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def text(value, field: str, max_len: int = 2000, required: bool = False, errors: list | None = None) -> str:
    value = (value or "").strip()
    if required and not value:
        if errors is not None:
            errors.append(f"{field} is required.")
    if len(value) > max_len:
        if errors is not None:
            errors.append(f"{field} must be {max_len} characters or fewer.")
        value = value[:max_len]
    return value


def username(value, errors: list | None = None) -> str:
    value = (value or "").strip().lower()
    if not USERNAME_RE.match(value):
        if errors is not None:
            errors.append("Username: use 3-32 letters, numbers, dots, dashes or underscores.")
    return value


def email(value, errors: list | None = None) -> str:
    value = (value or "").strip().lower()
    if not EMAIL_RE.match(value) or len(value) > 254:
        if errors is not None:
            errors.append("Enter a valid email address.")
    return value


def url(value, field: str, required: bool = False, errors: list | None = None) -> str:
    value = text(value, field, max_len=500, errors=errors)
    if not value:
        if required and errors is not None:
            errors.append(f"{field} is required.")
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        if errors is not None:
            errors.append(f"{field} must be a full http:// or https:// URL.")
        return ""
    return value


def integer(value, field: str, *, errors: list | None = None, minimum: int | None = None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        if errors is not None:
            errors.append(f"{field} must be a whole number.")
        return None
    if minimum is not None and number < minimum:
        if errors is not None:
            errors.append(f"{field} must be at least {minimum}.")
        return None
    return number


def local_datetime(value, field: str, required: bool = False, errors: list | None = None):
    """Parse an HTML datetime-local value into a naive UTC-normalised datetime."""
    value = (value or "").strip()
    if not value:
        if required and errors is not None:
            errors.append(f"{field} is required.")
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        if errors is not None:
            errors.append(f"{field} is not a valid date/time.")
        return None


def local_date(value, field: str, *, errors: list | None = None):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        if errors is not None:
            errors.append(f"{field} is not a valid date.")
        return None


def one_of(value, choices, field: str, *, errors: list | None = None) -> str:
    value = (value or "").strip()
    if value not in choices:
        if errors is not None:
            errors.append(f"Choose a valid {field}.")
        return ""
    return value
