#
# Copyright 2026 100 (croc100)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#

from django.shortcuts import render
from django.urls import reverse_lazy 
from django.views.generic import TemplateView, ListView, CreateView, UpdateView, DetailView 
from django.contrib.auth.mixins import UserPassesTestMixin 
from django.http import JsonResponse, Http404
from django.db.models import Q
from django.utils.dateparse import parse_date

# 모델 임포트
from .models import PlayerDailyStats, Player, Notice, Tournament, News, FeaturedItem


# ==========================================
# 0. 관리자 권한 제어 (Mixin)
# ==========================================
class AdminRequiredMixin(UserPassesTestMixin):
    """Staff 또는 Superuser 권한이 있는지 검증합니다."""
    def test_func(self):
        return self.request.user.is_authenticated and (self.request.user.is_staff or self.request.user.is_superuser)


# ==========================================
# 1. 메인 화면 (Home)
# ==========================================
class HomeView(TemplateView):
    template_name = 'core/home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['news'] = News.objects.all().order_by('-created_at')[:5]
        
        # [수정] is_published=True 인 공지만 노출되도록 필터링 추가
        context['notices'] = Notice.objects.filter(is_published=True).order_by('-is_pinned', '-publish_at')[:5]
        context['featured_items'] = FeaturedItem.objects.select_related('tournament').all()[:3]
        
        user = self.request.user
        if user.is_authenticated:
            context['greeting_name'] = user.nickname or user.username
            context['my_highlight'] = "오늘의 새로운 소식을 확인해보세요"
        else:
            context['greeting_name'] = "방문자"
            context['my_highlight'] = "로그인하고 내 전적을 관리해보세요"
        return context


# ==========================================
# 2. 캘린더 (Calendar)
# ==========================================
class CalendarView(TemplateView):
    template_name = 'core/calendar.html'

def calendar_events(request):
    tournaments = Tournament.objects.all()
    events = []
    for t in tournaments:
        events.append({
            'title': t.name,
            'start': t.start_date.isoformat() if t.start_date else None,
            'end': t.end_date.isoformat() if t.end_date else None,
            'url': t.external_url,
            'extendedProps': {
                'source': t.source,
                'region': t.region,
            }
        })
    return JsonResponse(events, safe=False)

class CalendarDayView(ListView):
    """지정한 날짜의 대회 목록을 보여주는 뷰"""
    model = Tournament
    template_name = 'core/calendar_day.html'
    context_object_name = 'tournaments'

    def get_queryset(self):
        date_str = self.kwargs.get('date_str')
        target_date = parse_date(date_str)
        
        if not target_date:
            raise Http404("잘못된 날짜 형식입니다.")

        return Tournament.objects.filter(
            Q(start_date__lte=target_date) & 
            (Q(end_date__gte=target_date) | Q(end_date__isnull=True))
        ).order_by('start_date')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['day'] = parse_date(self.kwargs.get('date_str'))
        return context


# ==========================================
# 3. 공지사항 (Notice)
# ==========================================
class NoticeListView(ListView):
    model = Notice
    template_name = 'core/notice_list.html'
    context_object_name = 'notices'
    paginate_by = 10

    def get_queryset(self):
        # [수정] is_published=True 인 공지만 노출되도록 필터링 추가
        queryset = Notice.objects.filter(is_published=True).order_by('-is_pinned', '-publish_at')
        category = self.request.GET.get('category')
        query = self.request.GET.get('q')

        if category:
            queryset = queryset.filter(category=category)
        if query:
            queryset = queryset.filter(title__icontains=query) | queryset.filter(content__icontains=query)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['categories'] = [
            ('NOTICE', '공지'),
            ('UPDATE', '업데이트'),
            ('EVENT', '이벤트'),
        ]
        return context

# [신규] 공지사항 작성 뷰
class NoticeCreateView(AdminRequiredMixin, CreateView):
    model = Notice
    template_name = 'core/notice_form.html'
    fields = ['title', 'category', 'content', 'is_published', 'show_as_page', 'publish_at', 'expire_at']
    success_url = reverse_lazy('core:notice_list')
    
    def form_valid(self, form):
        # 공지 작성자를 현재 로그인한 관리자로 자동 지정
        form.instance.author = self.request.user
        return super().form_valid(form)
        
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['mode'] = 'create'
        return context

# [신규] 공지사항 수정 뷰
class NoticeUpdateView(AdminRequiredMixin, UpdateView):
    model = Notice
    template_name = 'core/notice_form.html'
    fields = ['title', 'category', 'content', 'is_published', 'show_as_page', 'publish_at', 'expire_at']
    success_url = reverse_lazy('core:notice_list')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['mode'] = 'edit'
        return context


# ==========================================
# 4. 선수 검색 (Player Search)
# ==========================================
class PlayerSearchView(ListView):
    model = Player
    template_name = 'core/player_search.html'
    context_object_name = 'results'
    paginate_by = 20

    FILTER_OPTIONS = {
        'ages': ['20', '20대', '30', '30대', '40', '40대', '50', '50대', '오픈', '준장년', '초등', '중등', '대학부'],
        'levels': ['왕초심', '초심', '입문', 'D', 'C', 'B', 'A', 'S'],
        'genders': [('M', '남성'), ('F', '여성')]
    }

    def get_queryset(self):
        query = self.request.GET.get('q', '').strip()
        age = self.request.GET.get('age')
        level = self.request.GET.get('level')
        gender = self.request.GET.get('gender')

        if not any([query, age, level, gender]):
            return Player.objects.none()

        queryset = Player.objects.all()

        if query:
            queryset = queryset.filter(Q(name__icontains=query) | Q(club__icontains=query))
        
        if age:
            queryset = queryset.filter(daily_stats__category_age_band__icontains=age)
        if level:
            queryset = queryset.filter(daily_stats__category_level__icontains=level)
        if gender:
            queryset = queryset.filter(daily_stats__gender=gender)

        return queryset.distinct().order_by('name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filters'] = self.FILTER_OPTIONS
        context['query'] = self.request.GET.get('q', '')
        return context
    
class NoticeDetailView(DetailView):
    """공지사항 상세 페이지 뷰"""
    model = Notice
    template_name = 'core/notice_detail.html'
    context_object_name = 'notice'
    
    def get_queryset(self):
        # [권한 제어] 관리자는 비공개(is_published=False) 공지도 상세보기가 가능해야 합니다.
        if self.request.user.is_authenticated and (self.request.user.is_staff or self.request.user.is_superuser):
            return Notice.objects.all()
        # 일반 유저는 공개된 공지만 볼 수 있습니다.
        return Notice.objects.filter(is_published=True)
    

class PlayerDetailView(DetailView):
    """선수 상세 전적 페이지"""
    model = Player
    template_name = 'core/player_detail.html'
    context_object_name = 'player'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 선수의 모든 전적을 최신순으로 가져옴 (대회 정보 포함)
        stats = self.object.daily_stats.select_related('tournament').all().order_by('-date')
        context['stats'] = stats
        
        # 요약 통계 계산
        context['total_tournaments'] = stats.count()
        
        # 1위~3위 입상 횟수 계산
        context['total_medals'] = sum(1 for stat in stats if stat.rank and stat.rank <= 3)
        
        # 전체 승률 계산
        total_wins = sum(stat.win_count for stat in stats)
        total_losses = sum(stat.loss_count for stat in stats)
        total_matches = total_wins + total_losses
        
        context['total_wins'] = total_wins
        context['total_losses'] = total_losses
        context['win_rate'] = (total_wins / total_matches * 100) if total_matches > 0 else 0.0

        return context