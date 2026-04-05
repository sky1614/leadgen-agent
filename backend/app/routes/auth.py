from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user
from ..models import UserDB, ClientDB
from ..schemas import UserCreate
from ..utils import hash_password, verify_password, create_token, _user_dict

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    if db.query(UserDB).filter(UserDB.email == user.email).first():
        raise HTTPException(400, "Email already registered")
    # Create a default client for this user
    client = ClientDB(name=user.name, industry="other")
    db.add(client)
    db.flush()
    u = UserDB(
        email=user.email, name=user.name,
        hashed_password=hash_password(user.password),
        client_id=client.id, role="admin"
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return {"access_token": create_token({"sub": u.id, "client_id": client.id}), "token_type": "bearer", "user": _user_dict(u)}


@router.post("/login")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    u = db.query(UserDB).filter(UserDB.email == form.username).first()
    if not u or not verify_password(form.password, u.hashed_password):
        raise HTTPException(401, "Invalid credentials")
    return {"access_token": create_token({"sub": u.id, "client_id": u.client_id}), "token_type": "bearer", "user": _user_dict(u)}


@router.get("/me")
def me(cu: UserDB = Depends(get_current_user)):
    return _user_dict(cu)
