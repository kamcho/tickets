from django.contrib import admin
from django.urls import path
from .views import (
    login_view, logout_view, home_view, profile_view,
    ticket_create_view, ticket_detail_view,
    user_list_view, user_create_view,
    customer_list_view, customer_create_view, customer_detail_view,
    customer_search_api, agent_search_api,
)
from .views_assistant import (
    assistant_page, assistant_chat_api, assistant_chat_stream_api,
    category_suggest_api, whatsapp_webhook,
)
from .views_portal import (
    portal_home, portal_login, portal_logout,
    portal_ticket_list, portal_ticket_create, portal_ticket_detail,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", home_view, name="home"),
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
    path("profile/", profile_view, name="profile"),
    path("tickets/create/", ticket_create_view, name="ticket_create"),
    path("tickets/<str:ticket_id>/", ticket_detail_view, name="ticket_detail"),
    path("users/", user_list_view, name="user_list"),
    path("users/create/", user_create_view, name="user_create"),
    path("customers/", customer_list_view, name="customer_list"),
    path("customers/create/", customer_create_view, name="customer_create"),
    path("customers/<int:pk>/", customer_detail_view, name="customer_detail"),
    path("api/customers/search/", customer_search_api, name="customer_search_api"),
    path("api/agents/search/", agent_search_api, name="agent_search_api"),
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
