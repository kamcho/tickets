from django.urls import path
from .views import landing_page, login_view

urlpatterns = [
    path("", landing_page, name="landing"),
    path("login/", login_view, name="login"),
]
