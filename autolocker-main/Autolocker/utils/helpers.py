import re
import secrets
import string
import uuid
from datetime import datetime, timezone
from typing import Optional


# =========================
# LOG ID (collision-safe)
# =========================

def generate_log_id() -> str:
    """
    Enterprise-safe уникальный ID:
    LOCK-YYYYMMDD-XXXXXX
    """
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    unique = uuid.uuid4().hex[:8].upper()
    return f"LOCK-{today}-{unique}"


# =========================
# PASSWORD GENERATOR (CRYPTO SAFE)
# =========================

_SYMBOLS = "!@#$%^&*"


def generate_password(length: int = 14) -> str:
    """
    Криптографически безопасный пароль с гарантией сложности
    """

    length = max(length, 10)

    alphabet = string.ascii_letters + string.digits + _SYMBOLS

    while True:
        password = ''.join(secrets.choice(alphabet) for _ in range(length))

        # требования сложности
        if (
            any(c.islower() for c in password)
            and any(c.isupper() for c in password)
            and any(c.isdigit() for c in password)
            and any(c in _SYMBOLS for c in password)
        ):
            return password


# =========================
# LOCATION FORMATTER (BUG FIXED)
# =========================

def format_location(lat: Optional[float], lon: Optional[float]) -> str:
    """
    Безопасное форматирование координат (исправлен баг 0.0)
    """
    if lat is None or lon is None:
        return "Локация недоступна"

    try:
        return f"{float(lat):.4f}, {float(lon):.4f}"
    except (TypeError, ValueError):
        return "Локация недоступна"


# =========================
# APPLE ID VALIDATOR (STRICT)
# =========================

_APPLE_EMAIL_REGEX = re.compile(
    r"^[a-z0-9](?:[a-z0-9._%+-]{0,63})@"
    r"[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}$",
    re.IGNORECASE
)


def validate_apple_id(email: str) -> bool:
    """
    Строгая проверка Apple ID
    """
    if not email:
        return False

    email = email.strip()

    if len(email) > 254:
        return False

    if ".." in email:
        return False

    return bool(_APPLE_EMAIL_REGEX.match(email))


# =========================
# EXTRA ENTERPRISE UTIL
# =========================

def entropy_score(password: str) -> float:
    """
    Оценка стойкости пароля (0-1)
    """
    if not password:
        return 0.0

    score = 0.0

    if any(c.islower() for c in password):
        score += 0.25
    if any(c.isupper() for c in password):
        score += 0.25
    if any(c.isdigit() for c in password):
        score += 0.25
    if any(c in _SYMBOLS for c in password):
        score += 0.25

    # бонус за длину
    score += min(len(password) / 32, 0.25)

    return min(score, 1.0)


def now_iso() -> str:
    """
    Единый формат времени для всей системы
    """
    return datetime.now(timezone.utc).isoformat()