"""Bounded maintenance for ephemeral *new* platform security records.

A caller-owned transaction can invoke this from an approved future worker.
It does not delete durable audit/outbox or idempotency outcomes (retention
requires explicit C1-B approval) and is NOT scheduled in existing runtimes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from identity._persistence import AdminTokenRevocationRow, LoginAttemptRow
from projects._resource_persistence import CredentialLeaseRow

from ._browser_telemetry_persistence import BrowserTelemetryBudgetRow
from ._service_identity_persistence import ConsumedAssertionRow


async def prune_ephemeral_security_records(
    tx: AsyncSession,
    *,
    batch_size: int = 500,
) -> dict[str, int]:
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    now = datetime.now(UTC)
    old_lease_ids = list(
        await tx.scalars(
            select(CredentialLeaseRow.id)
            .where(CredentialLeaseRow.expires_at < now - timedelta(days=1))
            .order_by(CredentialLeaseRow.expires_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
    )
    if old_lease_ids:
        await tx.execute(delete(CredentialLeaseRow).where(CredentialLeaseRow.id.in_(old_lease_ids)))

    old_revoke_ids = list(
        await tx.scalars(
            select(AdminTokenRevocationRow.jti_digest)
            .where(AdminTokenRevocationRow.expires_at < now - timedelta(days=1))
            .order_by(AdminTokenRevocationRow.expires_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
    )
    if old_revoke_ids:
        await tx.execute(
            delete(AdminTokenRevocationRow).where(
                AdminTokenRevocationRow.jti_digest.in_(old_revoke_ids)
            )
        )

    old_assertion_ids = list(
        await tx.scalars(
            select(ConsumedAssertionRow.id)
            .where(ConsumedAssertionRow.expires_at < now - timedelta(days=1))
            .order_by(ConsumedAssertionRow.expires_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
    )
    if old_assertion_ids:
        await tx.execute(
            delete(ConsumedAssertionRow).where(ConsumedAssertionRow.id.in_(old_assertion_ids))
        )

    # Event payloads are NEVER persisted. Only minute-granularity
    # admission counters remain, and a bounded maintenance sweep limits
    # their long-term cardinality without touching consent or audit rows.
    old_browser_buckets = list(
        (
            await tx.execute(
                select(
                    BrowserTelemetryBudgetRow.user_id,
                    BrowserTelemetryBudgetRow.scope_kind,
                    BrowserTelemetryBudgetRow.scope_id,
                    BrowserTelemetryBudgetRow.minute_start,
                )
                .where(BrowserTelemetryBudgetRow.minute_start < now - timedelta(days=1))
                .order_by(BrowserTelemetryBudgetRow.minute_start)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
        ).tuples()
    )
    if old_browser_buckets:
        await tx.execute(
            delete(BrowserTelemetryBudgetRow).where(
                tuple_(
                    BrowserTelemetryBudgetRow.user_id,
                    BrowserTelemetryBudgetRow.scope_kind,
                    BrowserTelemetryBudgetRow.scope_id,
                    BrowserTelemetryBudgetRow.minute_start,
                ).in_(old_browser_buckets)
            )
        )

    old_attempt_ids = list(
        await tx.scalars(
            select(LoginAttemptRow.bucket_key)
            .where(
                LoginAttemptRow.last_failed_at < now - timedelta(days=1),
                or_(
                    LoginAttemptRow.blocked_until.is_(None),
                    LoginAttemptRow.blocked_until < now,
                ),
            )
            .order_by(LoginAttemptRow.last_failed_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
    )
    if old_attempt_ids:
        await tx.execute(
            delete(LoginAttemptRow).where(LoginAttemptRow.bucket_key.in_(old_attempt_ids))
        )
    return {
        "credential_leases": len(old_lease_ids),
        "admin_token_revocations": len(old_revoke_ids),
        "login_attempts": len(old_attempt_ids),
        "consumed_service_assertions": len(old_assertion_ids),
        "browser_telemetry_budgets": len(old_browser_buckets),
    }
