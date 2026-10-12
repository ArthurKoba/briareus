"""Private Web Hand lifecycle while verified OAuth and Cedar grants are pending."""

from hand_runtime import create_closed_hand_app

app = create_closed_hand_app(
    unavailable_code="WEB_OAUTH_AUTHORIZATION_UNAVAILABLE",
    health_fields={"authorization": "not_configured"},
)
