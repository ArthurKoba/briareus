"""Independent Resource Catalog owner: deny-by-default private Rauthy metadata.

Runtime-owned service peer, Platform Project/Team attestor and own-DB reader
must all be supplied by verified infrastructure before even read-only
resource metadata becomes available. Health does not confer access.
"""

from __future__ import annotations

from fastapi import FastAPI

from common.owner_runtime import OwnerIngressVerifier, create_owner_app
from projects._rauthy_catalog_reader import (
    CatalogMetadataReader,
    private_catalog_reader_router,
)


def create_resources_app(
    *,
    trusted_ingress: OwnerIngressVerifier | None = None,
    metadata_reader: CatalogMetadataReader | None = None,
) -> FastAPI:
    app = create_owner_app("resources", trusted_ingress=trusted_ingress)
    app.include_router(
        private_catalog_reader_router(
            reader=metadata_reader if trusted_ingress is not None else None
        )
    )
    return app


app = create_resources_app()
