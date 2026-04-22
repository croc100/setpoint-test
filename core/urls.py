# core/urls.py

from django.urls import path
from django.contrib.auth.views import LoginView, LogoutView

from .views import (
    HomeView, CalendarView, calendar_events, CalendarDayView,
    NoticeListView, NoticeCreateView, NoticeUpdateView, NoticeDetailView,
    PlayerSearchView, PlayerDetailView,
    TournamentListView, TournamentDetailView,
    ClubRankingView, ClubDetailView,
    TermsView, PrivacyView,
    MyPageView, PlayerClaimSearchView, PlayerClaimCreateView, PlayerClaimDeleteView,
    ManageDashboardView, ManageTournamentListView,
    TournamentCreateView, TournamentUpdateView, TournamentDeleteView,
    NoticeDeleteView,
)

app_name = 'core'

urlpatterns = [
    path('', HomeView.as_view(), name='home'),

    # 캘린더
    path('calendar/', CalendarView.as_view(), name='calendar'),
    path('calendar/events/', calendar_events, name='calendar_events'),
    path('calendar/day/<str:date_str>/', CalendarDayView.as_view(), name='calendar_day'),

    # 공지사항
    path('notice/', NoticeListView.as_view(), name='notice_list'),
    path('notice/create/', NoticeCreateView.as_view(), name='notice_create'),
    path('notice/<int:pk>/edit/', NoticeUpdateView.as_view(), name='notice_edit'),
    path('notice/<int:pk>/delete/', NoticeDeleteView.as_view(), name='notice_delete'),
    path('notice/<int:pk>/', NoticeDetailView.as_view(), name='notice_detail'),

    # 선수 검색 / 랭킹
    path('players/', PlayerSearchView.as_view(), name='player_search'),
    path('player/<int:pk>/', PlayerDetailView.as_view(), name='player_detail'),
    path('ranking/', ClubRankingView.as_view(), name='player_ranking'),
    path('club/', ClubDetailView.as_view(), name='club_detail'),

    # 대회 목록 / 상세
    path('tournaments/', TournamentListView.as_view(), name='tournament_list'),
    path('tournament/<int:pk>/', TournamentDetailView.as_view(), name='tournament_detail'),

    # 마이페이지 + 내 전적 찾기
    path('mypage/', MyPageView.as_view(), name='mypage'),
    path('mypage/claim/search/', PlayerClaimSearchView.as_view(), name='claim_search'),
    path('mypage/claim/<int:player_pk>/create/', PlayerClaimCreateView.as_view(), name='claim_create'),
    path('mypage/claim/<int:pk>/delete/', PlayerClaimDeleteView.as_view(), name='claim_delete'),

    # 관리자 대시보드
    path('manage/', ManageDashboardView.as_view(), name='manage_dashboard'),
    path('manage/tournaments/', ManageTournamentListView.as_view(), name='manage_tournaments'),
    path('manage/tournament/create/', TournamentCreateView.as_view(), name='tournament_create'),
    path('manage/tournament/<int:pk>/edit/', TournamentUpdateView.as_view(), name='tournament_edit'),
    path('manage/tournament/<int:pk>/delete/', TournamentDeleteView.as_view(), name='tournament_delete'),

    # 법적 문서
    path('terms/', TermsView.as_view(), name='terms'),
    path('privacy/', PrivacyView.as_view(), name='privacy'),

    # 인증
    path('login/', LoginView.as_view(template_name='core/login.html'), name='login'),
    path('logout/', LogoutView.as_view(next_page='/'), name='logout'),
]
