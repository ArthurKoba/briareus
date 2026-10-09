"""Team-only invariant checks; no persistence or HTTP dependencies."""

from common.platform_errors import AccessDenied
from common.platform_ids import UserId
from teams._domain import Team


def require_team_owner(team: Team, actor: UserId) -> None:
    if team.owner_user_id != actor:
        raise AccessDenied("Team owner required to administer membership or ownership")
