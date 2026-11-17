"""URL routes for the user API, mounted at /api/user/."""
from django.urls import path

from user import views

app_name = 'user'

urlpatterns = [
    path('register/', views.RegisterView.as_view(), name='register'),
    path('token/', views.LoginView.as_view(), name='token'),
    path('me/', views.ManageUserView.as_view(), name='me'),
]
