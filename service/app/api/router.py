"""Aggregates resource routers into one top-level router."""

from fastapi import APIRouter

from app.api.tokens import router as tokens_router
from app.api.users import router as users_router
from app.api.checkin import router as checkin_router
from app.api.teams import router as teams_router
from app.api.contests import router as contests_router
from app.api.trainings import router as trainings_router, alias_router as training_router
from app.api.extended_auth import router as extended_auth_router
from app.api.user_profile import router as user_profile_router
from app.api.benben import router as benben_router
from app.api.admin import router as admin_router
from app.api.admin_users import router as admin_users_router
from app.api.admin_plagiarism import router as admin_plagiarism_router
from app.api.judgement import router as judgement_router
from app.api.tickets import router as tickets_router
from app.api.forum import router as forum_router
from app.api.notifications import router as notifications_router
from app.api.admin_upload import router as admin_upload_router
from app.api.problems import router as problems_router
from app.api.submissions import router as submissions_router
from app.api.images import router as images_router
from app.api.shop import router as shop_router
from app.api.home_ads import router as home_ads_router
from app.api.friend_links import router as friend_links_router
from app.api.follow import router as follow_router
from app.api.messages import router as messages_router
from app.api.site_docs import router as site_docs_router
from app.api.reports import router as reports_router
from app.api.ranking import router as ranking_router
from app.api.group_chat import router as group_chat_router
from app.api.columns import (
    router as columns_router,
    alias_router as column_alias_router,
    articles_router,
    article_alias_router,
)
from app.api.site_settings import router as site_settings_router
from app.api.polls import router as polls_router
from app.api.battle import router as battle_router
from app.api.clipboards import router as clipboards_router
from app.api.otk import router as otk_router

api_router = APIRouter()
api_router.include_router(battle_router)
api_router.include_router(users_router)
api_router.include_router(checkin_router)
api_router.include_router(teams_router)
api_router.include_router(contests_router)
api_router.include_router(trainings_router)
api_router.include_router(training_router)
api_router.include_router(shop_router)
api_router.include_router(tokens_router)
api_router.include_router(extended_auth_router)
api_router.include_router(user_profile_router)
api_router.include_router(benben_router)
api_router.include_router(admin_router)
api_router.include_router(admin_users_router)
api_router.include_router(judgement_router)
api_router.include_router(tickets_router)
api_router.include_router(forum_router)
api_router.include_router(notifications_router)
api_router.include_router(admin_upload_router)
api_router.include_router(admin_plagiarism_router)
api_router.include_router(problems_router)
api_router.include_router(submissions_router)
api_router.include_router(images_router)
api_router.include_router(home_ads_router)
api_router.include_router(friend_links_router)
api_router.include_router(follow_router)
api_router.include_router(messages_router)
api_router.include_router(site_docs_router)
api_router.include_router(reports_router)
api_router.include_router(ranking_router)
api_router.include_router(columns_router)
api_router.include_router(column_alias_router)
api_router.include_router(group_chat_router)
api_router.include_router(articles_router)
api_router.include_router(article_alias_router)
api_router.include_router(site_settings_router)
api_router.include_router(polls_router)
api_router.include_router(clipboards_router)
api_router.include_router(otk_router)
