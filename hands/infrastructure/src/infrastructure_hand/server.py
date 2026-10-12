"""Private Infrastructure Hand lifecycle while verified OAuth and Cedar grants are pending."""

from pathlib import Path

from hand_runtime import create_diagnostic_hand_app

app = create_diagnostic_hand_app(
    hand="infrastructure",
    source_root=Path(__file__).resolve().parents[1],
    unavailable_code="INFRASTRUCTURE_OAUTH_AUTHORIZATION_UNAVAILABLE",
    health_fields={"authorization": "not_configured"},
)
