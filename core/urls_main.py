from django.urls import path
from .views import landing_page, login_view
from .views_assistant import (
    assistant_page, assistant_chat_api, assistant_chat_stream_api,
    category_suggest_api, whatsapp_webhook,
)
from .views_portal import (
    portal_home, portal_login, portal_logout,
    portal_ticket_list, portal_ticket_create, portal_ticket_detail,
)

urlpatterns = [
    path("", landing_page, name="landing"),
    path("login/", login_view, name="login"),
    path("portal/", portal_home, name="portal_home"),
    path("portal/login/", portal_login, name="portal_login"),
    path("portal/logout/", portal_logout, name="portal_logout"),
    path("portal/tickets/", portal_ticket_list, name="portal_ticket_list"),
    path("portal/tickets/create/", portal_ticket_create, name="portal_ticket_create"),
    path("portal/tickets/<str:ticket_id>/", portal_ticket_detail, name="portal_ticket_detail"),
    path("assistant/", assistant_page, name="assistant"),
    path("api/assistant/chat/", assistant_chat_api, name="assistant_chat_api"),
    path("api/assistant/chat/stream/", assistant_chat_stream_api, name="assistant_chat_stream_api"),
    path("api/categories/suggest/", category_suggest_api, name="category_suggest_api"),
    path("api/whatsapp/webhook/", whatsapp_webhook, name="whatsapp_webhook"),
]

from .url_handlers import handler400, handler403, handler404, handler500
