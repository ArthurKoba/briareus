"""Project ownership is exclusively User OR Team, never both."""

from dataclasses import dataclass

from common.platform_ids import PlatformProjectId, TeamId, UserId


class InvalidOwnership(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Project:
    id: PlatformProjectId
    name: str
    owner_user_id: UserId | None
    owner_team_id: TeamId | None
    version: int

    def __post_init__(self) -> None:
        if (self.owner_user_id is None) == (self.owner_team_id is None):
            raise InvalidOwnership("Project requires exactly one User or Team owner")
