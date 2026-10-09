"""Project owner transition policy, excluding session grant evaluation."""

from common.platform_errors import AccessDenied
from common.platform_ids import UserId
from projects._domain import Project


def require_personal_owner(project: Project, actor: UserId) -> None:
    if project.owner_user_id != actor:
        raise AccessDenied("personal Project owner required for transfer")
