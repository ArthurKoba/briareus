"""Optional isolated svc read-only metadata owner stage; not deployed."""

from pathlib import Path

from hand_runtime import TrustedMetadataPorts, build_protected_metadata_app
from starlette.applications import Starlette


def build_protected_svc_metadata_app(ports: TrustedMetadataPorts) -> Starlette:
    """Require true signed Project/Cedar/owner inspection, no legacy provider."""
    return build_protected_metadata_app(
        hand="svc",
        source_root=Path(__file__).resolve().parents[1],
        ports=ports,
    )
