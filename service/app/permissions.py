"""权限真源。"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.user import User


SUPER_ADMIN_UIDS: set[int] = {1, 68, 210}
PROTECTED_UIDS: set[int] = {0, 1, 3, 4, 68, 165, 210}


def is_white_list(user: "User") -> bool:
    """UID 白名单（成员见 :data:`SUPER_ADMIN_UIDS`）。最高层级。

    这里不写死具体编号：白名单会调整（曾为 {1, 3, 4, 68, 165, 210}，现为
    {1, 68, 210}），注释里写死过就会和常量失配、误导后来人。
    """
    return user.user_number in SUPER_ADMIN_UIDS


def is_protected(user: "User") -> bool:
    """受保护账号，不可被任何操作修改。"""
    return user.user_number in PROTECTED_UIDS


def is_super_admin(user: "User") -> bool:
    """超管（is_super_admin 字段为真，且不在白名单里）。"""
    return bool(user.is_super_admin) and not is_white_list(user)


def is_big_admin(user: "User") -> bool:
    """大管（不含更高层级）。"""
    return (
        bool(getattr(user, "is_big_admin", False))
        and not is_super_admin(user)
        and not is_white_list(user)
    )


def is_problem_admin(user: "User") -> bool:
    """题管（不含更高层级）。"""
    if is_white_list(user) or is_super_admin(user) or is_big_admin(user):
        return False
    return bool(user.can_manage_problems)


def is_community_admin(user: "User") -> bool:
    """社管（不含更高层级）。"""
    if is_white_list(user) or is_super_admin(user) or is_big_admin(user):
        return False
    return bool(user.can_manage_posts)


def is_any_admin(user: "User") -> bool:
    """任意管理角色（能进后台）。

    口径 = 管理名单公示的那几项能力：只要在名单里（白名单/超管/大管/题管/
    社管/Tag 管理/用户管理），就能进后台。别只认其中几项，否则会出现
    「名单公示了他，但他进不了后台」这种自相矛盾。
    """
    return (
        is_white_list(user)
        or is_super_admin(user)
        or is_big_admin(user)
        or is_problem_admin(user)
        or is_community_admin(user)
        or bool(getattr(user, "is_admin", False))
        or bool(getattr(user, "can_manage_users", False))
        or bool(getattr(user, "can_manage_tags", False))
    )


def is_top_admin(user: "User") -> bool:
    """白名单或超管。"""
    return is_white_list(user) or is_super_admin(user)


def role_rank(user: "User") -> int:
    if is_white_list(user):      return 5
    if is_super_admin(user):     return 4
    if is_big_admin(user):       return 3
    if is_problem_admin(user):   return 2
    if is_community_admin(user): return 1
    return 0


def can_modify_user(operator: "User", target: "User") -> bool:
    if is_protected(target):
        return False
    if operator.user_number == target.user_number:
        return False
    if is_white_list(target):
        return False
    if is_white_list(operator):
        return True
    if is_super_admin(operator):
        return not is_super_admin(target)
    if is_big_admin(operator):
        return not is_any_admin(target)
    # 「管理名单 → 用户管理」那一列的口径就是 :func:`can_manage_users`
    # （白名单/超管/大管，或持有该字段的人）。同一个列在别的入口都认它 ——
    # 单用户改权限（api/admin.py 的 gate）、批量（api/admin_users.py）、
    # 改头像（api/admin_upload.py）—— 只有这里漏了，结果「名单上写着用户管理、
    # 却改不了单个用户的资料」（403）。名单公示了谁，谁就干得了活。
    #
    # 目标范围与上面两个接口保持一致：受保护账号、白名单、自己都在前面挡掉了，
    # 剩下的只有「UID 2 以外的超管」不可动（UID 2 是历史遗留例外，见 update_user）。
    if can_manage_users(operator):
        return not (is_super_admin(target) and target.user_number != 2)
    return False


def can_reset_password(operator: "User") -> bool:
    return is_white_list(operator)


def can_ban_user(operator: "User") -> bool:
    return is_white_list(operator) or is_super_admin(operator) or is_big_admin(operator)


def can_request_ban(operator: "User") -> bool:
    return is_problem_admin(operator) or is_community_admin(operator)


def can_mute_user(operator: "User") -> bool:
    return (
        is_white_list(operator)
        or is_super_admin(operator)
        or is_big_admin(operator)
        or is_community_admin(operator)
    )


def can_mark_cheater(operator: "User") -> bool:
    return (
        is_white_list(operator)
        or is_super_admin(operator)
        or is_big_admin(operator)
        or is_problem_admin(operator)
    )


def can_grant_role(operator: "User", target_role: str) -> bool:
    if is_white_list(operator):
        return True
    if is_super_admin(operator):
        return target_role in ("problem_admin", "community_admin", "big_admin", "admin")
    return False


def can_revoke_role(operator: "User", target: "User") -> bool:
    if is_protected(target):
        return False
    if operator.user_number == target.user_number:
        return False
    if is_white_list(target):
        return False
    if is_white_list(operator):
        return True
    if is_super_admin(operator):
        return not is_super_admin(target)
    return False


def can_manage_problems(user: "User") -> bool:
    return (
        is_white_list(user)
        or is_super_admin(user)
        or is_big_admin(user)
        or is_problem_admin(user)
    )


def can_manage_community(user: "User") -> bool:
    return (
        is_white_list(user)
        or is_super_admin(user)
        or is_big_admin(user)
        or is_community_admin(user)
    )


def can_review_articles(user: "User") -> bool:
    """能否审核题解文章：白名单/超管/大管/题管/社管"""
    return (
        is_white_list(user)
        or is_super_admin(user)
        or is_big_admin(user)
        or is_problem_admin(user)
        or is_community_admin(user)
    )


def can_manage_users(user: "User") -> bool:
    """用户管理：白名单/超管/大管，或持有 ``can_manage_users`` 字段。

    为什么带大管：大管本来就能改普通用户（见 :func:`can_modify_user`、
    :func:`can_ban_user`），后台批量接口里「授予/撤销角色」另由
    :func:`can_grant_role` 单独把关，所以放他们进来不会多给权限。

    字段是「管理名单 → 用户管理」那一列的公示依据，也是后台批量改权限的
    放行依据，这里必须认它——否则公示了却干不了活。
    """
    return (
        is_white_list(user)
        or is_super_admin(user)
        or is_big_admin(user)
        or bool(getattr(user, "can_manage_users", False))
    )


def can_manage_tags(user: "User") -> bool:
    """Tag 管理：白名单/超管/大管，或持有 ``can_manage_tags`` 字段。

    与 :func:`can_manage_problems` / :func:`can_manage_community` 同构：
    高层级天然可以，持有对应字段的人也可以（字段只由白名单授予）。
    """
    return (
        is_white_list(user)
        or is_super_admin(user)
        or is_big_admin(user)
        or bool(getattr(user, "can_manage_tags", False))
    )


def can_manage_teams(user: "User") -> bool:
    return (
        is_white_list(user)
        or is_super_admin(user)
        or is_big_admin(user)
        or is_community_admin(user)
        or bool(getattr(user, "can_manage_users", False))
    )


# ================================================================
# 用户名身份色
# ================================================================
# 与前端 web/src/utils/userColor.ts **严格一致**，改一处必须同步另一处：
#   白名单/超管/大管（同紫）→ 题管（青）→ 社管（深蓝）→ 作弊者 → 封禁
#   → 自定义色 → 购买档位色
#
# 为什么要后端也算一份：公开资料等接口**刻意不下发 can_manage_* 管理标志**
# （见 schemas/user.py::PublicUserOut 的说明），前端只靠 payload 推不出题管 /
# 社管色，个人主页就会把他们的名字显示成购买档位色——与犇犇、私信、管理名单
# 里的颜色对不上。由后端把结果直接算好下发，全站就不会各算一套。
# 白名单 / 超管 / 大管统一紫色：与现网口径一致（金色是后来加的，已回退）。
# 这三个层级在界面上本来就是「同一档」的高层管理者，同色才不会看着像三套。
COLOR_WHITE_LIST = "#9C3DCF"
COLOR_SUPER_ADMIN = "#9C3DCF"
COLOR_BIG_ADMIN = "#9C3DCF"
COLOR_PROBLEM_ADMIN = "#13C2C2"
COLOR_COMMUNITY_ADMIN = "#0D47A1"
COLOR_CHEATER = "#AD8B00"
COLOR_BANNED = "#000000"

# 购买档位色（与 shop.py 的 COLOR_TIERS、前端 COLOR_TIER_MAP 同源）
COLOR_TIER_COLORS: dict[str, str] = {
    "gray": "#95a5a6",
    "blue": "#1890ff",
    "green": "#52c41a",
    "orange": "#fa8c16",
    "red": "#e74c3c",
}
COLOR_DEFAULT = COLOR_TIER_COLORS["gray"]


def user_name_color(user: "User | None") -> str:
    """用户名显示色（全站唯一口径）。

    层级判定直接复用上面的 ``is_whitelist`` / ``is_super_admin`` … —— 它们本身
    就是「不含更高层级」的互斥判定，所以这里的 if 链天然就是那份优先级表，
    不用再手写一遍比较。
    """
    if user is None:
        return COLOR_DEFAULT
    if is_white_list(user):
        return COLOR_WHITE_LIST
    if is_super_admin(user):
        return COLOR_SUPER_ADMIN
    if is_big_admin(user):
        return COLOR_BIG_ADMIN
    if is_problem_admin(user):
        return COLOR_PROBLEM_ADMIN
    if is_community_admin(user):
        return COLOR_COMMUNITY_ADMIN
    if bool(getattr(user, "is_cheater", False)):
        return COLOR_CHEATER
    if bool(getattr(user, "is_banned", False)):
        return COLOR_BANNED
    # 管理后台设置的自定义色（历史字段，用户自助不可改）优先于购买的档位色
    custom = (getattr(user, "username_color", None) or "").strip()
    if custom:
        return custom
    return COLOR_TIER_COLORS.get(getattr(user, "color_tier", None) or "gray", COLOR_DEFAULT)
