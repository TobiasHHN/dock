"""Platzhalter für den angemeldeten Nutzer (Task 0.6).

Solange F1 (Task 1.1) nicht fertig ist, wählt der Header `X-Demo-User: anna|ben|chef` den Nutzer
(ohne Header: Anna). Mit 1.1 wird dieses Modul durch JWT-Prüfung ersetzt, die Signatur von
`current_user` / `require_role` bleibt gleich.
"""
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel

from app.schemas.common import Actor


class CurrentUser(BaseModel):
    id: str
    name: str
    email: str
    roles: list[str]  # Rollen-Keys

    @property
    def actor(self) -> Actor:
        return Actor(type="user", id=self.id, name=self.name)


DEMO_USERS: dict[str, CurrentUser] = {
    "anna": CurrentUser(id="usr_anna", name="Anna Beispiel", email="anna@demo.local", roles=["einkauf"]),
    "ben": CurrentUser(id="usr_ben", name="Ben Mitarbeiter", email="ben@demo.local", roles=["mitarbeiter"]),
    "chef": CurrentUser(id="usr_chef", name="Chef Teamleiter", email="chef@demo.local", roles=["chef"]),
}


async def current_user(x_demo_user: Annotated[str | None, Header()] = None) -> CurrentUser:
    key = (x_demo_user or "anna").lower()
    user = DEMO_USERS.get(key)
    if user is None:
        raise HTTPException(status_code=401, detail=f"Unbekannter Demo-Nutzer '{key}' (anna|ben|chef)")
    return user


def require_role(*roles: str):
    async def dep(user: Annotated[CurrentUser, Depends(current_user)]) -> CurrentUser:
        if not set(roles) & set(user.roles):
            raise HTTPException(status_code=403, detail=f"Rolle {' oder '.join(roles)} erforderlich")
        return user

    return dep
