"""User model."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, JSON, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    # Integer (not BigInteger) so the PK auto-increments on SQLite
    # (INTEGER PRIMARY KEY -> rowid alias) as well as PostgreSQL (SERIAL).
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    # 用户编号 (UID)
    user_number: Mapped[int] = mapped_column(
        Integer, unique=True, index=True, nullable=False
    )

    # 手机号
    phone: Mapped[str | None] = mapped_column(
        String(20), unique=True, index=True, nullable=True
    )

    # 用户状态
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    is_banned: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    is_cheater: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )

    # 管理员权限
    is_super_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    is_big_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    is_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    can_speak: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    # 临时禁言到期时间（UTC）。can_speak=False 且本字段有值=限时禁言，
    # 到期后用户访问时自动恢复；can_speak=False 且本字段为 None=永久禁言。
    speak_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 恶意举报被禁言的累计次数（决定举报人的禁言时长梯度）
    malicious_report_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    # 内容违规（举报成立）被禁言的累计次数（决定作者的禁言时长梯度）
    content_violation_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    can_manage_users: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    can_manage_posts: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    can_assign_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    can_manage_problems: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    # Tag 管理权限：可授予/删除他人的 Tag 卡
    can_manage_tags: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )

    # 用户名颜色档位（自行购买升级）：gray/blue/green/orange/red。
    # 紫/青/棕为身份颜色（管理员/试用管理/作弊者），优先级高于本字段。
    color_tier: Mapped[str] = mapped_column(
        String(10), default="gray", server_default=text("'gray'"), nullable=False
    )
    # 用「经验」购买用户名颜色的累计花费（排行榜总经验需加回；
    # 用贡献购买的不计入，故只累计经验货币的部分）
    color_exp_spent: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )

    # 经验值：首次 AC 题目按难度获得（每题每用户仅一次）
    experience: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )

    # 贡献值：出题获得（按题目难度），贡献商店货币
    contribution: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )

    # 打卡：最近打卡日期（东八区）/ 当前连续天数 / 累计打卡天数
    last_checkin_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    checkin_streak: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    checkin_total: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )

    # 用户个性化信息
    avatar_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )

    # 主题商店：自定义背景。None = 默认背景；值形如
    # "/static/uploads/themes/xxx.png"（上传图）或 "preset:dawn"（内置渐变）
    theme_background: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    theme_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    # 主题商店「色相调整」：对主题色/顶栏 Logo/默认背景的色相偏移，
    # -180..180（度），0 = 默认配色。独立于 theme_enabled（未启用背景也生效）
    theme_hue: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    # 主题商店「深色主题」开关：light / dark。独立于 theme_enabled，
    # dark 时 html[data-theme="dark"] 覆盖 style.css 设计令牌
    theme_mode: Mapped[str] = mapped_column(
        String(10), default="light", server_default=text("'light'"), nullable=False
    )
    # 主题商店「洛谷风格主页」开关：cloud（默认，新版云图首页）/ luogu
    #（经典卡片首页：广告轮播 + 打卡卡 + 犇犇 + 训练题单）。
    # 只影响自己的首页观感，顶栏公告 / 犇犇浮窗等新功能不受影响
    home_style: Mapped[str] = mapped_column(
        String(10), default="cloud", server_default=text("'cloud'"), nullable=False
    )
    # 学术模式（个人设置里开）：开启后前端隐藏犇犇与灌水区，题目难度默认隐藏
    # （可在题库页手动展开）。纯粹的自律开关，不是权限，服务端不据此拒绝请求。
    academic_mode: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    # 个人偏好（偏好设置页）：代码模板为 JSON 字符串 {"cpp":..,"c":..,"python3":..}
    # （null = 全部用内置默认），code_font 为等宽字体 key（null = 默认 JetBrains Mono）
    code_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    code_font: Mapped[str | None] = mapped_column(String(40), nullable=True)
    user_tag: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    username_color: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    bio: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    # 管理员备注名（仅管理后台可见可编辑）
    remark: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    # 个人主页封面图
    cover_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    # 最后在线时间（60秒内视为在线）
    last_seen: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 上次改名时间（30 天冷却），None = 从未改过名或冷却已过
    last_username_change: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # 奖项认证：real_name 用于 OIerDB 检索，oierdb_uid 为选定条目 ID，
    # oi_awards 存 OIerDB 返回的奖项列表，oi_level 为审核通过后展示的等级，
    # award_cert_status: none / pending / approved / rejected
    real_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    oierdb_uid: Mapped[str | None] = mapped_column(String(100), nullable=True)
    oi_awards: Mapped[list | None] = mapped_column(JSON, nullable=True)
    oi_level: Mapped[str | None] = mapped_column(String(100), nullable=True)
    award_cert_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="none",
        server_default=text("'none'"),
    )

    # ===== 比赛等级分（算法见 services/contest_rating.py）=====
    # 初始 1500；只在后台勾了「计入等级分」且已结束的个人赛里结算，不回填历史。
    # rated_contests 是参加过几场结算赛 —— K 系数按它衰减（新手分动得快）。
    rating: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1500, server_default=text("1500"), index=True,
    )
    max_rating: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1500, server_default=text("1500"),
    )
    rated_contests: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"),
    )

    # Forward-ref string target is resolved from the Base registry; no import
    # needed here, which keeps user <-> refresh_token free of import cycles.
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    # 犇犇帖子关系
    benben_posts: Mapped[list["Benben"]] = relationship(
        "Benben", back_populates="user", cascade="all, delete-orphan"
    )

    # 关注关系
    following: Mapped[list["Follow"]] = relationship(  # noqa: F821
        "Follow", foreign_keys="Follow.follower_id", back_populates="follower",
        cascade="all, delete-orphan"
    )
    followers: Mapped[list["Follow"]] = relationship(  # noqa: F821
        "Follow", foreign_keys="Follow.followee_id", back_populates="followee",
        cascade="all, delete-orphan"
    )

    # Tag 卡（joined：序列化 display_tag 时需同步访问）
    tag_cards: Mapped[list["UserTagCard"]] = relationship(
        "UserTagCard",
        foreign_keys="UserTagCard.user_id",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def name_color(self) -> str:
        """用户名显示色（全站唯一口径，与前端 userColor.ts 一致）。

        由后端算好、随 payload 下发：公开资料等接口刻意不带 ``can_manage_*``
        管理标志，前端只靠 payload 推不出题管/社管色，个人主页就会把他们的
        名字显示成购买档位色，与犇犇/私信/管理名单里的颜色对不上。
        """
        from app.permissions import user_name_color

        return user_name_color(self)

    @property
    def display_tag(self) -> str:
        """全站统一显示的称号。

        优先级：作弊者（非管理员） > 佩戴中的 Tag 卡 > 管理后台设置的 user_tag >
        角色默认称号（UID 白名单 / 超级管理员 / 大管 / 题管 / 社管 / 用户管理 /
        Tag 管理 / 管理员）。

        角色链必须和「管理名单」公示的四列一致：少了 can_manage_users /
        can_manage_tags，被单独授予这两项的人在名单里会出现「有位置、没称号」。
        """
        from app.permissions import SUPER_ADMIN_UIDS
        is_any_admin = (
            self.user_number in SUPER_ADMIN_UIDS
            or bool(self.is_super_admin)
            or bool(self.is_big_admin)
            or bool(self.can_manage_problems)
            or bool(self.can_manage_posts)
            or bool(getattr(self, "can_manage_users", False))
            or bool(getattr(self, "can_manage_tags", False))
            or bool(self.is_admin)
        )
        # 作弊者（非管理员）强制显示「作弊者」，不被卡掩盖
        if self.is_cheater and not is_any_admin:
            return "作弊者"
        cards = self.tag_cards or []
        enabled = [c.name for c in cards if c.enabled]
        if enabled:
            return enabled[0]
        # 管理后台设置的自定义头衔（Tag 卡系统上线后此分支曾被遗漏）
        if self.user_tag:
            return self.user_tag
        # 角色默认身份称号（与 permissions.py 及后台口径严格对齐）
        if self.user_number in SUPER_ADMIN_UIDS:
            return "UID 白名单"
        if self.is_super_admin:
            return "超级管理员"
        if self.is_big_admin:
            return "大管"
        if self.can_manage_problems:
            return "题管"
        if self.can_manage_posts:
            return "社管"
        if getattr(self, "can_manage_users", False):
            return "用户管理"
        if getattr(self, "can_manage_tags", False):
            return "Tag 管理"
        if self.is_admin:
            return "管理员"
        return ""
