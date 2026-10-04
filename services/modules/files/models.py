from __future__ import annotations

from common.models import StrictModel


class ClientFile(StrictModel):
    download_url: str
    file_id: str | None = None
    mime_type: str | None = None
    file_name: str | None = None
