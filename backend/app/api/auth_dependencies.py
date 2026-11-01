from datetime import datetime, timezone
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import AuthSession, User, UserStatus
from app.db.session import get_db
from app.security.crypto import TokenValidationError, validate_access_token

_bearer = HTTPBearer(auto_error=False)


def get_current_auth(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer), session: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> tuple[User, AuthSession]:
    unauthorized = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication is required.", headers={"WWW-Authenticate": "Bearer"})
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized
    try:
        claims = validate_access_token(credentials.credentials, settings)
        user_id = UUID(str(claims["sub"]))
        session_id = UUID(str(claims["sid"]))
    except (TokenValidationError, KeyError, ValueError):
        raise unauthorized
    auth_session = session.get(AuthSession, session_id)
    user = session.get(User, user_id)
    now = datetime.now(timezone.utc)
    if auth_session is None or user is None or auth_session.user_id != user.id or auth_session.revoked_at is not None or auth_session.expires_at <= now or user.status != UserStatus.ACTIVE or user.deleted_at is not None:
        raise unauthorized
    auth_session.last_seen_at = now
    session.commit()
    return user, auth_session
