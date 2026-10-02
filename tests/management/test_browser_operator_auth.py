from __future__ import annotations

import pytest

from management.browser_operator_auth import (
    BrowserOperatorAuthError,
    issue_browser_operator_ticket,
    verify_browser_operator_ticket,
)


def test_browser_operator_ticket_round_trip() -> None:
    token = issue_browser_operator_ticket("secret", "admin", ttl_seconds=60, now=1000)
    verify_browser_operator_ticket(token, "secret", "admin", now=1059)


def test_browser_operator_ticket_rejects_wrong_secret_subject_and_expiry() -> None:
    token = issue_browser_operator_ticket("secret", "admin", ttl_seconds=60, now=1000)

    with pytest.raises(BrowserOperatorAuthError, match="signature"):
        verify_browser_operator_ticket(token, "other", "admin", now=1001)
    with pytest.raises(BrowserOperatorAuthError, match="subject"):
        verify_browser_operator_ticket(token, "secret", "other", now=1001)
    with pytest.raises(BrowserOperatorAuthError, match="expired"):
        verify_browser_operator_ticket(token, "secret", "admin", now=1061)
