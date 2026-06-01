
from django.urls import path
from .views import login_view, logout_view, home_view, ticket_create_view, ticket_detail_view, user_list_view, user_create_view

urlpatterns = [
    path("", home_view, name="home"),
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
    path("tickets/create/", ticket_create_view, name="ticket_create"),
    path("tickets/<str:ticket_id>/", ticket_detail_view, name="ticket_detail"),
    path("users/", user_list_view, name="user_list"),
    path("users/create/", user_create_view, name="user_create"),
]