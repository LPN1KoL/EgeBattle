from django.urls import path

from . import views

urlpatterns = [
    path('', views.home_view, name='home'),
    path('room/<uuid:room_uuid>/', views.auth_view, name='auth'),
    path('dev/room/<uuid:room_uuid>/', views.dev_auth_view, name='dev_auth'),
    path('lobby/<uuid:room_uuid>/', views.lobby_view, name='lobby'),
    path('game/<int:session_id>/', views.game_view, name='game'),
    path('result/<int:session_id>/', views.result_view, name='result'),
    path('leaderboard/', views.leaderboard_view, name='leaderboard'),
    path('profile/', views.profile_view, name='profile'),
    path('new-game/', views.new_game_view, name='new_game'),
    path('bot/webhook/', views.webhook_view, name='webhook'),
]
