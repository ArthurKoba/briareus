from __future__ import annotations

from fastapi import FastAPI
from starlette.testclient import TestClient

from management.domain.accounts import Account, AuthType, Provider
from management.presentation.api import ApiServices, build_internal_router


class AccountsStub:
    def __init__(self) -> None:
        self.account: Account | None = None
        self.credential = ""

    def get(self, selector: str, *, provider: Provider, enabled_only: bool = True) -> Account:
        del enabled_only
        if selector != "authenticated" or provider is not Provider.GITHUB or self.account is None:
            raise KeyError(selector)
        return self.account

    def create(self, account: Account, *, credential: str) -> Account:
        self.account = account
        self.credential = credential
        return account

    def update(self, account: Account) -> Account:
        self.account = account
        return account

    def set_credential(self, account_id: str, credential: str, *, provider: Provider) -> None:
        assert self.account is not None
        assert account_id == self.account.id
        assert provider is Provider.GITHUB
        self.credential = credential


class Noop:
    pass


def test_internal_github_reader_sync_creates_server_side_token_account() -> None:
    accounts = AccountsStub()
    services = ApiServices(
        accounts=accounts,  # type: ignore[arg-type]
        audit=Noop(),  # type: ignore[arg-type]
        oauth_sessions=Noop(),  # type: ignore[arg-type]
        runtime_settings=Noop(),  # type: ignore[arg-type]
        service_token="service-token",
    )
    app = FastAPI()
    app.include_router(build_internal_router(services))

    with TestClient(app) as client:
        response = client.put(
            "/internal/accounts/github/authenticated-reader",
            headers={"Authorization": "Bearer service-token"},
            json={"token": "oauth-secret", "login": "arthurkoba"},
        )

    assert response.status_code == 200
    assert response.json()["alias"] == "authenticated"
    assert response.json()["auth_type"] == "github_token"
    assert response.json()["login"] == "arthurkoba"
    assert "token" not in response.json()
    assert "credential" not in response.json()
    assert accounts.credential == "oauth-secret"
    assert accounts.account is not None
    assert accounts.account.auth_type is AuthType.GITHUB_TOKEN
