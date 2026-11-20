"""ORM models.

Importing this package registers every model on ``Base.metadata``. Alembic's
autogenerate depends on this — ``env.py`` does ``from app.models import Base``.
"""

from app.models.base import Base
from app.models.refresh_token import RefreshToken
from app.models.user import User
# Follow 必须跟着注册：Base.metadata.create_all() 只认这里 import 过的模型，
# 漏了它，测试库/本地库会直接没有 follows 表（关注接口 500）。
from app.models.follow import Follow
from app.models.benben import Benben
from app.models.judgement import JudgementLog
from app.models.ticket import Ticket, TicketReply
from app.models.forum import ForumPost, ForumComment
from app.models.notification import Notification
from app.models.direct_message import DirectMessage
from app.models.problem import Problem, ProblemAttachment
from app.models.submission import Submission, TestCase
from app.models.team import Team, TeamMember, TeamJoinRequest, TeamPost, TeamPostComment
from app.models.contest import Contest, ContestProblem, ContestParticipant, ContestTeam
from app.models.training import TrainingPlan, TrainingProblem, TrainingList
from app.models.image import UserImage
from app.models.tag_card import UserTagCard
from app.models.home_ad import HomeAd
from app.models.friend_link import FriendLink
from app.models.report import Report
from app.models.column import Column, ColumnArticle, ColumnInclusionRequest
from app.models.conversation import Conversation, ConversationMember, Message
from app.models.site_document import SiteDocument, SiteDocLog
from app.models.site_setting import SiteSetting
from app.models.battle import Battle, UserBattleStats
from app.models.clipboard import UserClipboard
from app.models.user_history import UsernameHistory, UserTagHistory
from app.models.virtual_contest import VirtualContest
from app.models.plagiarism import SimilarSubmissionPair
from app.models.poll import Poll, PollOption, PollVote

__all__ = ["Base", "User", "RefreshToken", "Follow", "Benben", "JudgementLog", "Ticket", "TicketReply", "ForumPost", "ForumComment", "Notification", "DirectMessage", "Problem", "ProblemAttachment", "Submission", "TestCase", "Team", "TeamMember", "TeamJoinRequest", "TeamPost", "TeamPostComment", "Contest", "ContestProblem", "ContestParticipant", "ContestTeam", "TrainingPlan", "TrainingProblem", "TrainingList", "UserImage", "UserTagCard", "HomeAd", "FriendLink", "Report", "Column", "ColumnArticle", "ColumnInclusionRequest", "Conversation", "ConversationMember", "Message", "SiteDocument", "SiteDocLog", "SiteSetting", "Battle", "UserBattleStats", "UserClipboard", "UsernameHistory", "UserTagHistory", "SimilarSubmissionPair", "VirtualContest", "Poll", "PollOption", "PollVote", "ContestRating"]
