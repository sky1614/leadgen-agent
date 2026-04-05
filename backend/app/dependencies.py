import hashlib
import time
from collections import defaultdict

from fastapi import Depends, HTTPException, Header
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from typing import Optional

from .config import SECRET_KEY, ALGORITHM
from .database import get_db
from .models import UserDB, ClientDB

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)

# ── API key rate limiter (100 req/min per key) ────────────────────────────────
_api_key_rate: dict = defaultdict(list)
_API_KEY_LIMIT = 100
_API_KEY_WINDOW = 60  # seconds

def _check_api_key_rate(key_prefix: str):
    now = time.time()
    window = now - _API_KEY_WINDOW
    _api_key_rate[key_prefix] = [t for t in _api_key_rate[key_prefix] if t > window]
    if len(_api_key_rate[key_prefix]) >= _API_KEY_LIMIT:
        raise HTTPException(429, "API key rate limit exceeded (100 req/min)")
    _api_key_rate[key_prefix].append(now)


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    x_api_key: Optional[str] = Header(default=None),
    db: Session = Depends(get_db)
) -> UserDB:
    # ── Path 1: API Key authentication ───────────────────────────────────────
    if x_api_key:
        key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
        client = db.query(ClientDB).filter(
            ClientDB.api_key_hash == key_hash,
            ClientDB.is_active == True
        ).first()
        if not client:
            raise HTTPException(401, "Invalid API key")
        _check_api_key_rate(client.api_key_prefix or client.id[:8])
        # Return first admin user for this client
        user = db.query(UserDB).filter(
            UserDB.client_id == client.id,
            UserDB.is_active == True
        ).first()
        if not user:
            raise HTTPException(401, "No active user for this API key")
        return user

    # ── Path 2: JWT Bearer authentication ─────────────────────────────────────
    if not token:
        raise HTTPException(401, "Not authenticated. Provide Bearer token or X-Api-Key header.")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(401, "Invalid token")
    except JWTError:
        raise HTTPException(401, "Invalid token")
    user = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not user:
        raise HTTPException(401, "User not found")
    return user


def get_current_client(cu: UserDB = Depends(get_current_user), db: Session = Depends(get_db)) -> ClientDB:
    if not cu.client_id:
        raise HTTPException(403, "No client associated with this user")
    client = db.query(ClientDB).filter(ClientDB.id == cu.client_id).first()
    if not client:
        raise HTTPException(403, "Client not found")
    return client
