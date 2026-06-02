
from django.urls import path
from .views import (
    login_view, logout_view, home_view, landing_page,
    ticket_create_view, ticket_detail_view,
    user_list_view, user_create_view,
    customer_list_view, customer_create_view, customer_detail_view,
    customer_search_api, agent_search_api,
)

urlpatterns = [
    path("", landing_page, name="landing"),
    path("home/", home_view, name="home"),
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
    path("tickets/create/", ticket_create_view, name="ticket_create"),
    path("tickets/<str:ticket_id>/", ticket_detail_view, name="ticket_detail"),
    path("users/", user_list_view, name="user_list"),
    path("users/create/", user_create_view, name="user_create"),
    path("customers/", customer_list_view, name="customer_list"),
    path("customers/create/", customer_create_view, name="customer_create"),
    path("customers/<int:pk>/", customer_detail_view, name="customer_detail"),
    path("api/customers/search/", customer_search_api, name="customer_search_api"),
    path("api/agents/search/", agent_search_api, name="agent_search_api"),
]