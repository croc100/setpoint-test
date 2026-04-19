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

        # [SE Fix] 좀비 데이터 누수 방지 (엄격한 기간 매칭)
        return Tournament.objects.filter(
            # 조건 1: 정상적으로 시작일과 종료일이 모두 있고, 타겟 날짜가 그 사이에 포함되는 경우
            Q(start_date__lte=target_date, end_date__gte=target_date) | 
            # 조건 2: 종료일이 누락(Null)된 과거 데이터의 경우, 시작일과 타겟 날짜가 정확히 일치하는 하루만 노출
            Q(start_date=target_date, end_date__isnull=True)
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
    """선수 상세 전적 페이지 (조별 상세 매치 데이터 포함)"""
    model = Player
    template_name = 'core/player_detail.html'
    context_object_name = 'player'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 선수의 모든 대회별 통계를 최신순으로 가져옴
        raw_stats = self.object.daily_stats.select_related('tournament').all().order_by('-date')
        
        processed_stats = []
        total_wins = 0
        total_losses = 0
        total_medals = 0
        
        for stat in raw_stats:
            # 1. 누적 데이터 합산
            total_wins += stat.win_count
            total_losses += stat.loss_count
            if stat.rank and stat.rank <= 3:
                total_medals += 1
                
            # 2. 파이프라인에서 수집한 데이터 가공 (프론트엔드 포맷팅)
            # - 만약 Match 스코어 데이터가 stat.matches.all() 같은 릴레이션으로 묶여있다고 가정
            # - DB 구조에 따라 stat.matches_data (JSON 필드) 등으로 접근할 수도 있음
            match_list = []
            
            # DB 모델 구조에 따라 아래 로직을 조정해야 함 (여기서는 일반적인 FK 릴레이션 가정)
            if hasattr(stat, 'matches'):
                for match in stat.matches.all():
                    match_list.append({
                        "is_win": match.is_win,
                        "opponent_names": match.opponent_names,
                        "opponent_club": match.opponent_club,
                        "my_score": match.my_score,
                        "op_score": match.op_score
                    })
            
            # 3. HTML 렌더링에 필요한 추가 필드 조합
            # (기존 모델에 이 필드들이 없다면 동적으로 할당해줌)
            stat.matches_list = match_list
            stat.category_full = f"{stat.gender or ''} {stat.category_age_band or ''} {stat.category_level or ''}".strip()
            
            # [핵심] final_status 계산 로직
            # DB에 명시적 필드가 없다면 득실과 랭크를 기반으로 자동 추론
            if not hasattr(stat, 'final_status') or not stat.final_status:
                if stat.rank == 1:
                    stat.final_status = '우승'
                elif stat.rank and stat.rank > 0:
                    stat.final_status = '본선 진출'
                elif stat.win_count > 0 or stat.loss_count > 0:
                    # 경기는 뛰었는데 랭크(입상)가 없다면 예선 탈락이거나 본선 초반 탈락
                    stat.final_status = '예선 탈락' 
                else:
                    stat.final_status = '출전 예정 / 기록 없음'
            
            processed_stats.append(stat)
            
        context['stats'] = processed_stats
        context['total_tournaments'] = len(processed_stats)
        context['total_medals'] = total_medals
        context['total_wins'] = total_wins
        context['total_losses'] = total_losses
        
        total_matches = total_wins + total_losses
        context['win_rate'] = (total_wins / total_matches * 100) if total_matches > 0 else 0.0

        return context