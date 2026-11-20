import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import settings

ALGORITHM = "HS256"


def _pw_bytes(password: str) -> bytes:
    # bcrypt only uses the first 72 bytes; truncate explicitly so long passwords don't error
    return password.encode()[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_pw_bytes(password), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(_pw_bytes(password), hashed.encode())


def create_access_token(subject: str | int, expires_delta: timedelta | None = None) -> str:
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return jwt.encode({"sub": str(subject), "exp": expire}, settings.SECRET_KEY, ALGORITHM)


API_TOKEN_PREFIX = "dfp_"  # "Dealflow personal"; makes leaked tokens easy to spot and scan for


def generate_api_token() -> str:
    return API_TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_api_token(token: str) -> str:
    # tokens are long and random, so a fast hash is enough (unlike passwords)
    return hashlib.sha256(token.encode()).hexdigest()
