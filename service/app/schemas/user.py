"""用户的 Pydantic 模型。"""

from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


def _decode_code_template_json(v):
    """ORM 的 code_template 列存的是 JSON 字符串，对外统一解码成字典。

    response_model 会逐字段校验：str 直接塞进 dict 字段 → ValidationError → 500。
    因为没保存过模板的用户该列是 None（能过校验），只有保存过模板的人炸——
    个人主页/用户列表/改资料等 UserOut 系接口全中。脏数据一律回 None。
    """
    if v is None or isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            data = json.loads(v)
        except ValueError:
            return None
        return data if isinstance(data, dict) else None
    return None


def _clean_phone(v):
    """手机号展示层清洗：不合规的历史脏数据一律转 None，不抛 500。

    - None / 空字符串 → None
    - 11 位且符合大陆手机号格式 → 原样保留
    - 其他 → None
    """
    if v is None or v == "":
        return None
    if not isinstance(v, str):
        return None
    if len(v) == 11 and v[0] == "1" and v[1] in "23456789" and v.isdigit():
        return v
    return None


class UserCreate(BaseModel):
    username: str = Field(
        min_length=3,
        max_length=50,
        pattern=r"^[A-Za-z0-9_]+$",
        description="用户名，3-50 位字母、数字或下划线",
    )
    email: EmailStr | None = Field(None, description="邮箱地址（邮箱注册时必填）")
    phone: str | None = Field(
        None,
        min_length=11,
        max_length=11,
        pattern=r"^1[3-9]\d{9}$",
        description="手机号（中国大陆 11 位，手机注册时必填）",
    )
    # 72 字符上限用于规避 bcrypt 72 字节的静默截断（ASCII 场景）。
    password: str = Field(min_length=8, max_length=72, description="密码，8-72 位")
    email_token: str | None = Field(None, description="邮箱验证令牌（邮箱注册时必填）")
    email_code: str | None = Field(None, description="邮箱验证码（邮箱注册时必填）")
    phone_token: str | None = Field(None, description="手机验证令牌（手机注册时必填）")
    phone_code: str | None = Field(None, description="手机验证码（手机注册时必填）")


class UserLogin(BaseModel):
    identifier: str = Field(description="用户名、UID、手机或电子邮箱")
    password: str = Field(description="密码")
    captcha: str | None = Field(None, description="兼容用图形验证码")
    captcha_id: str | None = Field(None, description="兼容用验证码ID")
    captcha_verify_param: str | None = Field(None, description="ESA AI 验证码验签参数")


class UserTagCardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="卡 ID")
    name: str = Field(description="Tag 名称")
    enabled: bool = Field(description="是否佩戴中")
    granter_id: int | None = Field(None, description="授予者用户ID（商店兑换为None）")
    granter_name: str | None = Field(None, description="授予者用户名")
    created_at: datetime | None = Field(None, description="授予时间")


class UsernameHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="记录ID")
    user_id: int = Field(description="目标用户ID")
    operator_id: int | None = Field(None, description="操作者ID")
    operator_name: str | None = Field(None, description="操作者用户名")
    is_self: bool = Field(False, description="是否本人修改")
    old_username: str = Field(description="修改前用户名")
    new_username: str = Field(description="修改后用户名")
    created_at: datetime = Field(description="修改时间")


class UserTagHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="记录ID")
    user_id: int = Field(description="目标用户ID")
    operator_id: int | None = Field(None, description="操作者ID")
    operator_name: str | None = Field(None, description="操作者用户名")
    action: str = Field(description="操作动作")
    action_label: str = Field(description="动作描述")
    tag_name: str = Field(description="Tag名称")
    created_at: datetime = Field(description="操作时间")


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="用户 ID")
    username: str = Field(description="用户名")
    email: str = Field(description="邮箱（展示用，不做严格格式校验）")
    user_number: int = Field(description="用户编号")
    phone: str | None = Field(None, description="手机号（展示用，脏数据自动置空）")

    @field_validator("phone", mode="before")
    @classmethod
    def _clean_phone_field(cls, v):
        return _clean_phone(v)
    is_active: bool = Field(description="是否启用")
    is_banned: bool = Field(description="是否被封禁")
    is_admin: bool = Field(description="是否管理员")
    is_super_admin: bool = Field(description="是否超级管理员")
    is_big_admin: bool = Field(False, description="是否大管理员")
    is_cheater: bool = Field(description="是否作弊者")
    can_speak: bool = Field(description="发言权限")
    speak_until: datetime | None = Field(None, description="限时禁言到期时间（UTC），null=未禁言或永久禁言")
    malicious_report_count: int = Field(0, description="恶意举报被禁言次数")
    content_violation_count: int = Field(0, description="内容违规被禁言次数")
    can_manage_users: bool = Field(description="用户管理权限")
    can_manage_posts: bool = Field(description="帖子管理权限")
    can_manage_problems: bool = Field(description="题目管理权限")
    can_assign_admin: bool = Field(description="授予管理员权限")
    can_manage_tags: bool = Field(False, description="Tag 管理权限")
    color_tier: str = Field("gray", description="用户名颜色档位 gray/blue/green/orange/red")
    color_exp_spent: int = Field(0, description="用经验购买用户名颜色的累计花费")
    # 比赛等级分（只在 is_rated 的个人赛结算；未参加过就是 1500）
    rating: int = Field(1500, description="比赛等级分")
    max_rating: int = Field(1500, description="历史最高等级分")
    rated_contests: int = Field(0, description="已结算的比赛场次")
    tag_cards: list[UserTagCardOut] = Field(default_factory=list, description="Tag 卡")
    display_tag: str = Field("", description="全站统一显示的称号")
    experience: int = Field(description="经验值")
    contribution: int = Field(0, description="贡献值（出题获得）")
    theme_background: str | None = Field(None, description="自定义背景（URL 或 preset:xxx）")
    theme_enabled: bool = Field(False, description="是否启用自定义背景主题")
    theme_hue: int = Field(0, description="主题色相偏移 -180..180（度），0 = 默认")
    theme_mode: str = Field("light", description="界面主题 light / dark（深色主题开关）")
    home_style: str = Field("cloud", description="主页风格 cloud（云图）/ luogu（经典洛谷式）")
    code_template: dict[str, str] | None = Field(
        None, description="个人代码模板（按语言；缺省语言用内置默认）"
    )

    @field_validator("code_template", mode="before")
    @classmethod
    def _decode_code_template(cls, v):
        return _decode_code_template_json(v)
    code_font: str | None = Field(None, description="编辑器等宽字体 key（null = 默认）")
    avatar_url: str | None = Field(None, description="头像URL")
    cover_url: str | None = Field(None, description="个人主页封面URL")
    user_tag: str | None = Field(None, description="用户标签")
    username_color: str | None = Field(None, description="用户名颜色")
    bio: str | None = Field(None, description="个人简介")
    last_seen: datetime | None = Field(None, description="最后在线时间")
    last_username_change: datetime | None = Field(None, description="上次改名时间（30 天冷却）")
    followers_count: int = Field(0, description="粉丝数")
    following_count: int = Field(0, description="关注数")
    is_following: bool = Field(False, description="当前用户是否关注了该用户")
    real_name: str | None = Field(None, description="真实姓名（奖项认证用）")
    oierdb_uid: str | None = Field(None, description="OIerDB 条目 ID")
    oi_awards: list | None = Field(None, description="OIerDB 奖项数据")
    oi_level: str | None = Field(None, description="OI 等级（审核通过后展示）")
    award_cert_status: str = Field("none", description="奖项认证状态 none/pending/approved/rejected")
    created_at: datetime = Field(description="创建时间")


class SelfUserOut(UserOut):
    """**本人专属**响应：比 :class:`UserOut` 多出只有自己该看到的偏好字段。

    只许用在「返回当前登录用户自己」的端点上（``/users/me`` 系列）。
    他人可见的响应一律走 :class:`PublicUserOut`；谁要新加私有偏好字段，
    加在这里而不是 ``UserOut``——``UserOut`` 是共享基类，一旦被拿去序列化
    别人，加在它上面的字段就跟着一起泄了。
    """

    academic_mode: bool = Field(
        False, description="学术模式：隐藏犇犇/灌水区，题目难度默认隐藏（仅本人可见）"
    )


class PublicUserOut(BaseModel):
    """公开用户主页/公开查询端点的精简响应。

    与 :class:`UserOut` 相比剔除了隐私与内部字段：
    ``email``、``phone``、``real_name``、``code_template``、``code_font``、
    ``is_active``、``can_speak``/``speak_until``、恶意/违规计数、
    ``last_username_change``、``oierdb_uid`` 以及全部 ``can_manage_*``、
    ``can_assign_admin``、``can_manage_tags`` 管理标志——
    公开端点（可匿名访问）不应泄露这些信息。
    保留主页展示所需字段与角色徽章（is_admin 等，主页公开显示）。
    ``/users/me`` 与管理后台继续使用 ``SelfUserOut`` / ``UserOut`` / ``UserAdminResponse``。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="用户 ID")
    username: str = Field(description="用户名")
    user_number: int = Field(description="用户编号")
    avatar_url: str | None = None
    cover_url: str | None = None
    bio: str | None = None
    color_tier: str = "gray"
    # 比赛等级分：个人主页要显示，所以放进公开资料（不敏感）
    rating: int = 1500
    max_rating: int = 1500
    rated_contests: int = 0
    username_color: str | None = None
    # 用户名显示色（后端算好的身份色，含题管/社管——公开端点不下发
    # can_manage_* 标志，前端自己推不出来，会导致主页与其它界面颜色不符）
    name_color: str = ""
    user_tag: str | None = None
    display_tag: str = ""
    tag_cards: list[UserTagCardOut] = Field(default_factory=list)
    experience: int = 0
    contribution: int = 0
    # 角色徽章（主页公开显示，非敏感）
    is_admin: bool = False
    is_super_admin: bool = False
    is_big_admin: bool = False
    is_banned: bool = False
    is_cheater: bool = False
    # 在线状态徽章
    last_seen: datetime | None = None
    # 关注统计（由端点动态附加）
    followers_count: int = 0
    following_count: int = 0
    is_following: bool = False
    # 奖项展示
    oi_level: str | None = None
    oi_awards: list | None = None
    award_cert_status: str = "none"
    # 个性化展示偏好（主页渲染用，非敏感）
    theme_background: str | None = None
    theme_enabled: bool = False
    theme_hue: int = 0
    theme_mode: str = "light"
    home_style: str = "cloud"
    # 编辑器偏好：非凭证类信息，保留以兼容 UserOut 系模板回传回归契约
    code_template: dict[str, str] | None = None
    code_font: str | None = None
    created_at: datetime | None = None

    @field_validator("code_template", mode="before")
    @classmethod
    def _decode_code_template_public(cls, v):
        return _decode_code_template_json(v)


class UserProfileUpdate(BaseModel):
    # 用户自助更新仅允许这些字段；user_tag / username_color 属于管理性质，
    # 只能由管理员在管理后台修改（见 UserAdminUpdate）
    username: str | None = Field(None, min_length=3, max_length=50, description="用户名")
    bio: str | None = Field(None, description="个人简介")
    avatar_url: str | None = Field(None, description="头像URL")


class PasswordUpdate(BaseModel):
    old_password: str = Field(description="旧密码")
    new_password: str = Field(min_length=8, max_length=72, description="新密码")


class UserAdminUpdate(BaseModel):
    """管理员用户更新模式"""
    username: str | None = Field(None, min_length=3, max_length=50, description="用户名")
    email: EmailStr | None = Field(None, description="邮箱")
    bio: str | None = Field(None, max_length=500, description="个人简介")
    avatar_url: str | None = Field(None, max_length=500, description="头像URL")
    user_tag: str | None = Field(None, max_length=100, description="用户标签")
    username_color: str | None = Field(None, max_length=20, description="用户名颜色")
    remark: str | None = Field(None, max_length=100, description="管理员备注名")

    # 管理员权限字段（仅管理员可修改）
    is_admin: bool | None = Field(None, description="管理员权限")
    is_super_admin: bool | None = Field(None, description="超级管理员权限")
    is_big_admin: bool | None = Field(None, description="大管理员权限")
    can_manage_users: bool | None = Field(None, description="用户管理权限")
    can_manage_posts: bool | None = Field(None, description="帖子管理权限")
    can_manage_problems: bool | None = Field(None, description="题目管理权限")
    can_assign_admin: bool | None = Field(None, description="授予管理员权限")
    can_speak: bool | None = Field(None, description="发言权限")
    is_banned: bool | None = Field(None, description="封禁状态")
    is_cheater: bool | None = Field(None, description="作弊者标记")


class UserAdminResponse(BaseModel):
    """管理员用户响应模式"""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="用户 ID")
    username: str = Field(description="用户名")
    email: str = Field(description="邮箱（展示用，不做严格格式校验）")
    user_number: int = Field(description="用户编号")
    phone: str | None = Field(None, description="手机号（展示用，脏数据自动置空）")

    @field_validator("phone", mode="before")
    @classmethod
    def _clean_phone_field(cls, v):
        return _clean_phone(v)
    is_active: bool = Field(description="是否启用")
    is_banned: bool = Field(description="是否被封禁")
    is_cheater: bool = Field(description="是否作弊者")
    is_super_admin: bool = Field(description="是否超级管理员")
    is_big_admin: bool = Field(False, description="是否大管理员")
    is_admin: bool = Field(description="是否管理员")
    can_speak: bool = Field(description="发言权限")
    speak_until: datetime | None = Field(None, description="限时禁言到期时间（UTC）")
    malicious_report_count: int = Field(0, description="恶意举报被禁言次数")
    content_violation_count: int = Field(0, description="内容违规被禁言次数")
    can_manage_users: bool = Field(description="用户管理权限")
    can_manage_posts: bool = Field(description="帖子管理权限")
    can_manage_problems: bool = Field(description="题目管理权限")
    can_assign_admin: bool = Field(description="授予管理员权限")
    can_manage_tags: bool = Field(False, description="Tag 管理权限")
    color_tier: str = Field("gray", description="用户名颜色档位 gray/blue/green/orange/red")
    color_exp_spent: int = Field(0, description="用经验购买用户名颜色的累计花费")
    # 比赛等级分（只在 is_rated 的个人赛结算；未参加过就是 1500）
    rating: int = Field(1500, description="比赛等级分")
    max_rating: int = Field(1500, description="历史最高等级分")
    rated_contests: int = Field(0, description="已结算的比赛场次")
    tag_cards: list[UserTagCardOut] = Field(default_factory=list, description="Tag 卡")
    display_tag: str = Field("", description="全站统一显示的称号")
    experience: int = Field(description="经验值")
    contribution: int = Field(0, description="贡献值（出题获得）")
    theme_background: str | None = Field(None, description="自定义背景（URL 或 preset:xxx）")
    theme_enabled: bool = Field(False, description="是否启用自定义背景主题")
    theme_hue: int = Field(0, description="主题色相偏移 -180..180（度），0 = 默认")
    theme_mode: str = Field("light", description="界面主题 light / dark（深色主题开关）")
    home_style: str = Field("cloud", description="主页风格 cloud（云图）/ luogu（经典洛谷式）")
    code_template: dict[str, str] | None = Field(
        None, description="个人代码模板（按语言；缺省语言用内置默认）"
    )

    @field_validator("code_template", mode="before")
    @classmethod
    def _decode_code_template(cls, v):
        return _decode_code_template_json(v)
    code_font: str | None = Field(None, description="编辑器等宽字体 key（null = 默认）")
    avatar_url: str | None = Field(None, description="头像URL")
    cover_url: str | None = Field(None, description="个人主页封面URL")
    user_tag: str | None = Field(None, description="用户标签")
    username_color: str | None = Field(None, description="用户名颜色")
    bio: str | None = Field(None, description="个人简介")
    remark: str | None = Field(None, description="管理员备注名")
    last_seen: datetime | None = Field(None, description="最后在线时间")
    last_username_change: datetime | None = Field(None, description="上次改名时间（30 天冷却）")
    followers_count: int = Field(0, description="粉丝数")
    following_count: int = Field(0, description="关注数")
    is_following: bool = Field(False, description="当前用户是否关注了该用户")
    real_name: str | None = Field(None, description="真实姓名（奖项认证用）")
    oierdb_uid: str | None = Field(None, description="OIerDB 条目 ID")
    oi_awards: list | None = Field(None, description="OIerDB 奖项数据")
    oi_level: str | None = Field(None, description="OI 等级（审核通过后展示）")
    award_cert_status: str = Field("none", description="奖项认证状态 none/pending/approved/rejected")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")
