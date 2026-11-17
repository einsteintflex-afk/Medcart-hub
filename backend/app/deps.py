import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .db import get_db
from .models import PROFESSIONAL_ROLES, ProviderProfile, Role, User, VerificationStatus
from .security import decode_token

bearer = HTTPBearer(auto_error=False)


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if not cred:
        raise HTTPException(401, "Not authenticated")
    try:
        uid = decode_token(cred.credentials, "access")
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")
    u = db.get(User, uid)
    if not u or not u.is_active:
        raise HTTPException(401, "Account disabled")
    return u


def require_roles(*roles: Role):
    def dep(u: User = Depends(current_user)) -> User:
        if u.role not in roles and u.role != Role.admin:
            raise HTTPException(403, "Insufficient role")
        return u
    return dep


def require_admin(u: User = Depends(current_user)) -> User:
    if u.role != Role.admin:
        raise HTTPException(403, "Admin only")
    return u


def verified_professional(*roles: Role):
    """Only an administrator-approved professional of the given role(s) may act."""
    allowed = set(roles) or PROFESSIONAL_ROLES

    def dep(u: User = Depends(current_user), db: Session = Depends(get_db)) -> User:
        if u.role not in allowed:
            raise HTTPException(403, "Insufficient role")
        p = db.get(ProviderProfile, u.id)
        if not p or p.status != VerificationStatus.approved:
            raise HTTPException(403, "Your professional credentials are not yet verified")
        return u
    return dep


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
