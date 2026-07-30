from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from apps.gateway.auth.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    validate_email_address,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# In-memory store stub for user accounts (syncs with Database models in full execution)
_user_db_stub: dict = {}
_token_blacklist: set = set()


class UserRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, description="User password (min 8 chars)")
    organization_name: Optional[str] = "Default Org"


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    is_verified: bool
    is_active: bool
    organization_id: Optional[str] = None


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(req: UserRegisterRequest) -> UserResponse:
    """Register a new user account."""
    if not validate_email_address(req.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email address format",
        )

    if req.email.lower() in _user_db_stub:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already exists",
        )

    user_id = str(uuid.uuid4())
    org_id = str(uuid.uuid4())
    hashed_pwd = hash_password(req.password)

    user_record = {
        "id": user_id,
        "email": req.email.lower(),
        "password_hash": hashed_pwd,
        "is_verified": False,
        "is_active": True,
        "organization_id": org_id,
    }

    _user_db_stub[req.email.lower()] = user_record

    return UserResponse(
        id=user_id,
        email=req.email.lower(),
        is_verified=False,
        is_active=True,
        organization_id=org_id,
    )


@router.post("/login", response_model=TokenResponse)
async def login(req: UserLoginRequest) -> TokenResponse:
    """Authenticate credentials and issue JWT Access and Refresh Tokens."""
    user = _user_db_stub.get(req.email.lower())
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive",
        )

    token_data = {"sub": user["id"], "email": user["email"]}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(req: RefreshTokenRequest) -> TokenResponse:
    """Issue a new access and refresh token pair using a valid refresh token."""
    if req.refresh_token in _token_blacklist:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
        )

    try:
        payload = decode_token(req.refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid token type, expected refresh token",
            )
        
        user_id = payload.get("sub")
        email = payload.get("email")
        
        token_data = {"sub": user_id, "email": email}
        new_access_token = create_access_token(token_data)
        new_refresh_token = create_refresh_token(token_data)

        # Blacklist old refresh token
        _token_blacklist.add(req.refresh_token)

        return TokenResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            token_type="bearer",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )


@router.post("/logout")
async def logout(authorization: Optional[str] = Header(None)) -> dict:
    """Revoke active JWT token session."""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        _token_blacklist.add(token)
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
async def get_current_user(authorization: Optional[str] = Header(None)) -> UserResponse:
    """Retrieve details for currently authenticated user."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )

    token = authorization.split(" ")[1]
    if token in _token_blacklist:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
        )

    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type for authorization",
            )

        email = payload.get("email")
        user = _user_db_stub.get(email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        return UserResponse(
            id=user["id"],
            email=user["email"],
            is_verified=user["is_verified"],
            is_active=user["is_active"],
            organization_id=user["organization_id"],
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )
