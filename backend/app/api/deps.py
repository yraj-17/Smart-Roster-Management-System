from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.db import SessionLocal


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def get_actor(x_actor: Annotated[str | None, Header(max_length=80)] = None) -> str:
    """Who is making the change, recorded in the audit log.

    There is no authentication in this assessment build; the UI sends the
    operator's name in the X-Actor header.
    """
    return (x_actor or "ops.manager").strip() or "ops.manager"


DB = Annotated[Session, Depends(get_session)]
Actor = Annotated[str, Depends(get_actor)]
