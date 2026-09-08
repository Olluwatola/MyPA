from sqlalchemy.orm import Session

from src.app import models
from src.app.core.security import get_password_hash
from tests.conftest import fake


def create_user(db: Session, is_super_user: bool = False) -> models.User:
    _user = models.User(
        first_name=fake.first_name(),
        last_name=fake.last_name(),
        email=fake.email(),
        hashed_password=get_password_hash(fake.password()),
        is_superuser=is_super_user,
    )

    db.add(_user)
    db.commit()
    db.refresh(_user)

    return _user
