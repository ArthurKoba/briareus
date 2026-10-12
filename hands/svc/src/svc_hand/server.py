"""Private SVC Hand; provider admission awaits real Rauthy and Cedar decisions."""

from pathlib import Path

from hand_runtime import create_closed_hand_app

app = create_closed_hand_app(
    hand="svc",
    source_root=Path(__file__).resolve().parents[1],
    unavailable_code="SVC_PRIVATE_C2_TRANSPORT_PENDING",
)
