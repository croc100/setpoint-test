#
# Copyright 2026 100 (croc100)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#

from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse_lazy, reverse
from django.views.generic import TemplateView, ListView, CreateView, UpdateView, DetailView, View, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import JsonResponse, Http404
from django.db.models import Q, Prefetch, Count, Sum, FloatField, ExpressionWrapper
from django.db.models.functions import Coalesce
from django.core.paginator import Paginator
from django.utils.dateparse import parse_date
import datetime

# 모델 임포트
from .models import PlayerDailyStats, Player, Notice, Tournament, News, FeaturedItem, PlayerClaim


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
        context['news'] = News.objects.all().order_by('-created_at')[:4]
        context['notices'] = Notice.objects.filter(is_published=True).order_by('-is_pinned', '-publish_at')[:5]

        # 금주의 대회: 오늘부터 7일 이내 시작하는 대회 자동 필터
        today = datetime.date.today()
        week_later = today + datetime.timedelta(days=7)
        context['this_week_tournaments'] = Tournament.objects.filter(
            start_date__gte=today,
            start_date__lte=week_later,
        ).order_by('start_date')[:4]

        # 동호회 랭킹 TOP 5 (입상 횟수 기준)
        context['top_clubs'] = list(
            PlayerDailyStats.objects
            .exclude(player__club='')
            .values('player__club', 'player__source')
            .annotate(
                gold_count=Count('id', filter=Q(final_status='우승')),
                medal_count=Count('id', filter=Q(final_status__in=['우승', '준우승', '3위'])),
            )
            .filter(medal_count__gt=0)
            .order_by('-medal_count', '-gold_count')[:5]
        )

        user = self.request.user
        if user.is_authenticated:
            context['greeting_name'] = user.nickname or user.username
        else:
            context['greeting_name'] = "방문자"
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

    # 급수 표기는 정규화된 값과 UI 표시값이 다르므로 (value, label) 튜플 사용
    # 강한 순: S조 > 자강 > 준자강 > A조 > B조 > C조 > D조 > E조 > F조
    FILTER_OPTIONS = {
        'ages': [
            '20대', '30대', '40대', '50대',
            '오픈', '준장년', '초등', '중등', '대학부',
        ],
        'levels': [
            ('S조',   'S조'),
            ('자강',  '자강'),
            ('준자강','준자강'),
            ('A조',   'A조'),
            ('B조',   'B조'),
            ('C조',   'C조'),
            ('D조',   'D조'),
            ('E조',   'E조 (초심)'),
            ('F조',   'F조 (왕초심)'),
            ('1부', '1부'), ('2부', '2부'), ('3부', '3부'), ('4부', '4부'),
        ],
        'genders': [('남성', '남성'), ('여성', '여성'), ('혼합', '혼합')],
    }

    def get_queryset(self):
        query  = self.request.GET.get('q', '').strip()      # 이름 검색
        club   = self.request.GET.get('club', '').strip()   # 동호회 검색 (별도)
        age    = self.request.GET.get('age', '').strip()
        level  = self.request.GET.get('level', '').strip()
        gender = self.request.GET.get('gender', '').strip()

        if not any([query, club, age, level, gender]):
            return Player.objects.none()

        qs = Player.objects.all()

        if query:
            qs = qs.filter(name__icontains=query)
        if club:
            qs = qs.filter(club__icontains=club)

        # stat 필터 — 정규화된 값이므로 exact 매칭
        stat_q = Q()
        if age:
            stat_q &= Q(daily_stats__category_age_band__icontains=age)
        if level:
            stat_q &= Q(daily_stats__category_level=level)
        if gender:
            stat_q &= Q(daily_stats__gender=gender)
        if stat_q:
            qs = qs.filter(stat_q)

        # 검색 조건에 맞는 stat만 Prefetch → 템플릿에서 matched_stats.0으로 접근
        stat_filter = Q()
        if age:
            stat_filter &= Q(category_age_band__icontains=age)
        if level:
            stat_filter &= Q(category_level=level)
        if gender:
            stat_filter &= Q(gender=gender)

        matched_qs = PlayerDailyStats.objects.select_related('tournament').order_by('-date')
        if stat_filter:
            matched_qs = matched_qs.filter(stat_filter)

        qs = qs.distinct().prefetch_related(
            Prefetch('daily_stats', queryset=matched_qs, to_attr='matched_stats')
        ).order_by('name')

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filters'] = self.FILTER_OPTIONS
        context['query']   = self.request.GET.get('q', '')
        context['club_q']  = self.request.GET.get('club', '')
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
    

# ==========================================
# 5. 대회 목록 / 대회 상세 (Tournament)
# ==========================================
SOURCE_META = {
    'BAEF':       {'label': '배프',   'color': 'violet'},
    'WEEKUK':     {'label': '위꾹',   'color': 'orange'},
    'SPONET':     {'label': '스포넷', 'color': 'red'},
    'FACECOK':    {'label': '페이스콕','color': 'blue'},
    'NEARMINTON': {'label': '우동배', 'color': 'green'},
}

class TournamentListView(ListView):
    model = Tournament
    template_name = 'core/tournament_list.html'
    context_object_name = 'tournaments'
    paginate_by = 20

    def get_queryset(self):
        today = datetime.date.today()
        q      = self.request.GET.get('q', '').strip()
        source = self.request.GET.get('source', '').strip()
        status = self.request.GET.get('status', '').strip()
        region = self.request.GET.get('region', '').strip()

        qs = Tournament.objects.filter(start_date__isnull=False).order_by('-start_date')

        if q:
            qs = qs.filter(name__icontains=q)
        if source:
            qs = qs.filter(source=source)
        if region:
            qs = qs.filter(region=region)
        if status == 'upcoming':
            qs = qs.filter(start_date__gte=today)
        elif status == 'ongoing':
            qs = qs.filter(start_date__lte=today, end_date__gte=today)
        elif status == 'finished':
            qs = qs.filter(end_date__lt=today)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['query']    = self.request.GET.get('q', '')
        context['source_q'] = self.request.GET.get('source', '')
        context['status_q'] = self.request.GET.get('status', '')
        context['region_q'] = self.request.GET.get('region', '')
        context['sources']  = list(SOURCE_META.items())
        context['status_choices'] = [
            ('upcoming', '예정'),
            ('ongoing',  '진행중'),
            ('finished', '종료'),
        ]
        # 지역 목록 (데이터가 있는 것만 추출)
        context['regions'] = (
            Tournament.objects
            .filter(start_date__isnull=False)
            .exclude(region='')
            .values_list('region', flat=True)
            .distinct()
            .order_by('region')
        )
        return context


class TournamentDetailView(DetailView):
    model = Tournament
    template_name = 'core/tournament_detail.html'
    context_object_name = 'tournament'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        t = self.object

        stats = (
            PlayerDailyStats.objects
            .filter(tournament=t)
            .select_related('player')
            .order_by('category_age_band', 'category_level', 'gender', 'rank', 'player__name')
        )

        # 카테고리별 그룹핑
        from collections import defaultdict, OrderedDict
        raw = defaultdict(list)
        for s in stats:
            gender_label = s.gender or ''
            age_label    = s.category_age_band or ''
            level_label  = s.category_level or ''
            key = f"{gender_label} {age_label} {level_label}".strip() or '기타'
            raw[key].append(s)

        context['categories']         = dict(raw)
        context['total_participants'] = stats.count()
        context['source_meta']        = SOURCE_META.get(t.source, {'label': t.source, 'color': 'gray'})
        return context


# ==========================================
# 6. 선수 랭킹 (Player Ranking)
# ==========================================
class PlayerRankingView(ListView):
    model = Player
    template_name = 'core/player_ranking.html'
    context_object_name = 'players'
    paginate_by = 50

    LEVEL_OPTIONS = [
        ('S조',    'S조'),
        ('자강',   '자강'),
        ('준자강', '준자강'),
        ('A조',    'A조'),
        ('B조',    'B조'),
        ('C조',    'C조'),
        ('D조',    'D조'),
        ('E조',    'E조 (초심)'),
        ('F조',    'F조 (왕초심)'),
        ('1부', '1부'), ('2부', '2부'), ('3부', '3부'), ('4부', '4부'),
    ]

    def get_queryset(self):
        source = self.request.GET.get('source', '').strip()
        level  = self.request.GET.get('level', '').strip()
        sort   = self.request.GET.get('sort', 'tournaments')

        qs = Player.objects.annotate(
            total_tournaments=Count('daily_stats', distinct=True),
            total_wins=Coalesce(Sum('daily_stats__win_count'), 0),
            total_losses=Coalesce(Sum('daily_stats__loss_count'), 0),
            medal_count=Count(
                'daily_stats',
                filter=Q(daily_stats__final_status__in=['우승', '준우승', '3위'])
            ),
        ).filter(total_tournaments__gt=0)

        if source:
            qs = qs.filter(source=source)
        if level:
            qs = qs.filter(level=level)

        if sort == 'medals':
            qs = qs.order_by('-medal_count', '-total_tournaments')
        elif sort == 'wins':
            qs = qs.order_by('-total_wins', '-total_tournaments')
        else:  # tournaments (기본)
            qs = qs.order_by('-total_tournaments', '-total_wins')

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['source_q']    = self.request.GET.get('source', '')
        context['level_q']     = self.request.GET.get('level', '')
        context['sort_q']      = self.request.GET.get('sort', 'tournaments')
        context['sources']     = list(SOURCE_META.items())
        context['levels']      = self.LEVEL_OPTIONS
        context['sort_options'] = [
            ('tournaments', '출전 많은 순'),
            ('medals',      '입상 많은 순'),
            ('wins',        '승리 많은 순'),
        ]
        # 랭킹 오프셋 (페이지네이션 고려)
        page = self.request.GET.get('page', 1)
        try:
            page = int(page)
        except (ValueError, TypeError):
            page = 1
        context['rank_offset'] = (page - 1) * self.paginate_by
        return context


# ==========================================
# 7. 동호회 랭킹 (Club Ranking)
# ==========================================
class ClubRankingView(View):
    template_name = 'core/club_ranking.html'
    paginate_by = 50

    AGE_OPTIONS   = ['20대', '30대', '40대', '50대', '오픈', '준장년', '초등', '중등', '대학부']
    # 강한 순 정렬
    LEVEL_OPTIONS = [
        ('S조',    'S조'),
        ('자강',   '자강'),
        ('준자강', '준자강'),
        ('A조',    'A조'),
        ('B조',    'B조'),
        ('C조',    'C조'),
        ('D조',    'D조'),
        ('E조',    'E조 (초심)'),
        ('F조',    'F조 (왕초심)'),
        ('1부', '1부'), ('2부', '2부'), ('3부', '3부'), ('4부', '4부'),
    ]
    SORT_OPTIONS  = [
        ('medals',  '입상 많은 순'),
        ('gold',    '우승 많은 순'),
        ('entries', '출전 많은 순'),
        ('players', '선수 많은 순'),
    ]

    def get(self, request):
        source = request.GET.get('source', '').strip()
        age    = request.GET.get('age', '').strip()
        level  = request.GET.get('level', '').strip()
        sort   = request.GET.get('sort', 'medals')

        qs = PlayerDailyStats.objects.exclude(player__club='')

        if source:
            qs = qs.filter(player__source=source)
        if age:
            qs = qs.filter(category_age_band__icontains=age)
        if level:
            qs = qs.filter(category_level=level)

        clubs = (
            qs.values('player__club', 'player__source')
            .annotate(
                player_count = Count('player', distinct=True),
                entry_count  = Count('id'),
                gold_count   = Count('id', filter=Q(final_status='우승')),
                medal_count  = Count('id', filter=Q(
                    final_status__in=['우승', '준우승', '3위']
                )),
            )
            .filter(entry_count__gte=1)
        )

        if sort == 'gold':
            clubs = clubs.order_by('-gold_count', '-medal_count', '-entry_count')
        elif sort == 'entries':
            clubs = clubs.order_by('-entry_count', '-medal_count')
        elif sort == 'players':
            clubs = clubs.order_by('-player_count', '-medal_count')
        else:  # medals (기본)
            clubs = clubs.order_by('-medal_count', '-gold_count', '-entry_count')

        page_number = request.GET.get('page', 1)
        try:
            page_number = int(page_number)
        except (ValueError, TypeError):
            page_number = 1

        paginator = Paginator(clubs, self.paginate_by)
        page_obj  = paginator.get_page(page_number)

        return render(request, self.template_name, {
            'page_obj':     page_obj,
            'clubs':        page_obj.object_list,
            'paginator':    paginator,
            'is_paginated': paginator.num_pages > 1,
            'source_q':     source,
            'age_q':        age,
            'level_q':      level,
            'sort_q':       sort,
            'sources':      list(SOURCE_META.items()),
            'ages':         self.AGE_OPTIONS,
            'levels':       self.LEVEL_OPTIONS,
            'sort_options': self.SORT_OPTIONS,
            'rank_offset':  (page_number - 1) * self.paginate_by,
        })


# ==========================================
# 8. 동호회 상세 (Club Detail)
# ==========================================
class ClubDetailView(View):
    template_name = 'core/club_detail.html'

    def get(self, request):
        source = request.GET.get('source', '').strip()
        club   = request.GET.get('club',   '').strip()

        if not source or not club:
            raise Http404("동호회 정보가 없습니다.")

        # ── 소속 선수 목록 (입상 > 출전 순) ──
        members = (
            Player.objects.filter(source=source, club=club)
            .annotate(
                entry_count  = Count('daily_stats'),
                gold_count   = Count('daily_stats', filter=Q(daily_stats__final_status='우승')),
                medal_count  = Count('daily_stats', filter=Q(
                    daily_stats__final_status__in=['우승', '준우승', '3위']
                )),
            )
            .order_by('-medal_count', '-entry_count')
        )

        # ── 최근 참가 대회 (최신 대회 10개) ──
        recent_raw = (
            PlayerDailyStats.objects
            .filter(player__source=source, player__club=club)
            .select_related('tournament', 'player')
            .order_by('-date')[:60]
        )

        from collections import OrderedDict
        recent_tournaments = OrderedDict()
        for s in recent_raw:
            tid = s.tournament_id
            if tid not in recent_tournaments:
                if len(recent_tournaments) >= 10:
                    break
                recent_tournaments[tid] = {
                    'tournament': s.tournament,
                    'results':   [],
                }
            recent_tournaments[tid]['results'].append(s)

        # ── 전체 집계 ──
        totals = (
            PlayerDailyStats.objects
            .filter(player__source=source, player__club=club)
            .aggregate(
                total_entries = Count('id'),
                total_players = Count('player', distinct=True),
                gold_count    = Count('id', filter=Q(final_status='우승')),
                medal_count   = Count('id', filter=Q(
                    final_status__in=['우승', '준우승', '3위']
                )),
            )
        )

        return render(request, self.template_name, {
            'club':               club,
            'source':             source,
            'source_meta':        SOURCE_META.get(source, {'label': source, 'color': 'gray'}),
            'members':            members,
            'recent_tournaments': list(recent_tournaments.values()),
            'totals':             totals,
        })


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
            # rank는 CharField — int 변환 후 비교
            try:
                rank_int = int(stat.rank) if stat.rank else None
            except (ValueError, TypeError):
                rank_int = None
            if rank_int and rank_int <= 3:
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
            if not stat.final_status:
                if rank_int == 1:
                    stat.final_status = '우승'
                elif rank_int and rank_int <= 4:
                    stat.final_status = '입상'
                elif rank_int:
                    stat.final_status = '본선 진출'
                elif stat.win_count > 0 or stat.loss_count > 0:
                    stat.final_status = '예선 탈락'
                else:
                    stat.final_status = '기록 없음'
            
            processed_stats.append(stat)
            
        context['stats'] = processed_stats
        context['total_tournaments'] = len(processed_stats)
        context['total_medals'] = total_medals
        context['total_wins'] = total_wins
        context['total_losses'] = total_losses

        total_matches = total_wins + total_losses
        context['win_rate'] = (total_wins / total_matches * 100) if total_matches > 0 else 0.0

        # 팔로우 여부
        user = self.request.user
        context['is_following'] = (
            user.is_authenticated and
            user.following_players.filter(pk=self.object.pk).exists()
        )
        context['follower_count'] = self.object.followers.count()


# ==========================================
# 9. 선수 팔로우 토글
# ==========================================

class FollowToggleView(LoginRequiredMixin, View):
    """선수 팔로우/언팔로우 AJAX 토글"""
    def post(self, request, pk):
        player = get_object_or_404(Player, pk=pk)
        user = request.user
        if user.following_players.filter(pk=pk).exists():
            user.following_players.remove(player)
            following = False
        else:
            user.following_players.add(player)
            following = True
        return JsonResponse({
            'following': following,
            'count': player.followers.count(),
        })


# ==========================================
# 10. 선수 비교
# ==========================================

def _player_stat_summary(player):
    """선수 1명의 요약 통계 반환"""
    stats = PlayerDailyStats.objects.filter(player=player)
    agg = stats.aggregate(wins=Sum('win_count'), losses=Sum('loss_count'))
    wins   = agg['wins'] or 0
    losses = agg['losses'] or 0
    total  = stats.count()
    gold   = stats.filter(final_status='우승').count()
    medals = stats.filter(final_status__in=['우승', '준우승', '3위']).count()
    total_matches = wins + losses
    win_rate = round(wins / total_matches * 100, 1) if total_matches > 0 else 0.0
    recent = list(stats.select_related('tournament').order_by('-date')[:5])
    return {
        'player':    player,
        'total':     total,
        'wins':      wins,
        'losses':    losses,
        'gold':      gold,
        'medals':    medals,
        'win_rate':  win_rate,
        'recent':    recent,
    }


class PlayerCompareView(TemplateView):
    template_name = 'core/player_compare.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        p1_pk = self.request.GET.get('p1', '').strip()
        p2_pk = self.request.GET.get('p2', '').strip()

        p1 = _player_stat_summary(get_object_or_404(Player, pk=p1_pk)) if p1_pk else None
        p2 = _player_stat_summary(get_object_or_404(Player, pk=p2_pk)) if p2_pk else None
        context['p1'] = p1
        context['p2'] = p2
        context['p1_pk'] = p1_pk
        context['p2_pk'] = p2_pk
        if p1 and p2:
            context['compare_rows'] = [
                ('참가 대회', p1['total'],    p2['total'],    '회'),
                ('총 승',     p1['wins'],     p2['wins'],     '승'),
                ('총 패',     p1['losses'],   p2['losses'],   '패'),
                ('🥇 우승',   p1['gold'],     p2['gold'],     '회'),
                ('입상',      p1['medals'],   p2['medals'],   '회'),
                ('승률',      p1['win_rate'], p2['win_rate'], '%'),
            ]
        return context


# ==========================================
# 11. 법적 문서 (이용약관 / 개인정보처리방침)
# ==========================================

class TermsView(TemplateView):
    template_name = 'core/terms.html'

class PrivacyView(TemplateView):
    template_name = 'core/privacy.html'


# ==========================================
# 12. 마이페이지 (My Page)
# ==========================================

SOURCE_COLORS = {
    'BAEF': ('bg-violet-100 text-violet-700', '배프'),
    'WEEKUK': ('bg-orange-100 text-orange-700', '위꾹'),
    'SPONET': ('bg-red-100 text-red-700', '스포넷'),
    'FACECOK': ('bg-blue-100 text-blue-700', '페이스콕'),
    'NEARMINTON': ('bg-green-100 text-green-700', '우동배'),
}

class MyPageView(LoginRequiredMixin, View):
    template_name = 'core/mypage.html'
    login_url = '/login/'

    def get(self, request, *args, **kwargs):
        if request.user.is_staff or request.user.is_superuser:
            return redirect('core:manage_dashboard')

        claims = (
            PlayerClaim.objects
            .filter(user=request.user)
            .select_related('player')
            .prefetch_related('player__daily_stats__tournament')
        )

        claimed_data = []
        for claim in claims:
            player = claim.player
            stats_qs = player.daily_stats.filter(is_verified=True)
            agg = stats_qs.aggregate(
                total=Count('id'),
                wins=Sum('win_count'),
                losses=Sum('loss_count'),
            )
            gold = stats_qs.filter(rank__in=['1', '1위', '우승']).count()
            recent = stats_qs.select_related('tournament').order_by('-date')[:5]
            badge_class, badge_label = SOURCE_COLORS.get(player.source, ('bg-gray-100 text-gray-600', player.source))
            claimed_data.append({
                'claim': claim,
                'player': player,
                'total': agg['total'] or 0,
                'wins': agg['wins'] or 0,
                'losses': agg['losses'] or 0,
                'gold': gold,
                'recent': recent,
                'badge_class': badge_class,
                'badge_label': badge_label,
            })

        # 팔로잉 선수 + 최근 전적 (prefetch로 N+1 방지)
        following_players = (
            request.user.following_players
            .prefetch_related(
                Prefetch(
                    'daily_stats',
                    queryset=PlayerDailyStats.objects
                        .select_related('tournament')
                        .order_by('-date')[:3],
                    to_attr='recent_stats',
                )
            )
            .order_by('name')
        )

        return render(request, self.template_name, {
            'claimed_data': claimed_data,
            'following_players': following_players,
        })

    def post(self, request, *args, **kwargs):
        """닉네임 변경 처리"""
        nickname = request.POST.get('nickname', '').strip()
        if nickname:
            if len(nickname) > 20:
                return JsonResponse({'ok': False, 'error': '닉네임은 20자 이하여야 해요'})
            request.user.nickname = nickname
            request.user.save(update_fields=['nickname'])
            return JsonResponse({'ok': True, 'nickname': nickname})
        return JsonResponse({'ok': False, 'error': '닉네임을 입력해주세요'})


class PlayerClaimSearchView(LoginRequiredMixin, View):
    """내 전적 찾기 — 이름으로 선수 검색 (AJAX)"""
    login_url = '/login/'

    def get(self, request):
        q = request.GET.get('q', '').strip()
        if len(q) < 1:
            return JsonResponse({'results': []})

        players = (
            Player.objects
            .filter(name__icontains=q)
            .exclude(claims__user=request.user)   # 이미 클레임한 선수 제외
            .annotate(stat_count=Count('daily_stats'))
            .order_by('-stat_count')[:30]
        )

        results = []
        for p in players:
            badge_class, badge_label = SOURCE_COLORS.get(p.source, ('bg-gray-100 text-gray-600', p.source))
            results.append({
                'id': p.id,
                'name': p.name,
                'club': p.club,
                'level': p.level or '',
                'source': p.source,
                'badge_label': badge_label,
                'badge_class': badge_class,
                'stat_count': p.stat_count,
            })

        return JsonResponse({'results': results})


class PlayerClaimCreateView(LoginRequiredMixin, View):
    """선수 클레임 생성"""
    login_url = '/login/'

    def post(self, request, player_pk):
        if request.user.is_staff or request.user.is_superuser:
            return JsonResponse({'ok': False, 'error': '관리자 계정은 클레임을 사용할 수 없어요.'}, status=403)

        player = get_object_or_404(Player, pk=player_pk)
        claim, created = PlayerClaim.objects.get_or_create(user=request.user, player=player)
        return JsonResponse({'ok': True, 'created': created, 'player_name': player.name})


class PlayerClaimDeleteView(LoginRequiredMixin, View):
    """선수 클레임 해제"""
    login_url = '/login/'

    def post(self, request, pk):
        claim = get_object_or_404(PlayerClaim, pk=pk, user=request.user)
        claim.delete()
        return JsonResponse({'ok': True})


# ==========================================
# 10. 관리자 대시보드 (Admin Dashboard)
# ==========================================
class ManageDashboardView(AdminRequiredMixin, View):
    template_name = 'core/manage/dashboard.html'

    def get(self, request):
        stats = {
            'tournament_total':   Tournament.objects.count(),
            'tournament_draft':   Tournament.objects.filter(status='draft').count(),
            'notice_total':       Notice.objects.count(),
            'player_total':       Player.objects.count(),
        }
        recent_notices = Notice.objects.order_by('-publish_at')[:5]
        return render(request, self.template_name, {
            'stats':         stats,
            'recent_notices': recent_notices,
        })


class ManageTournamentListView(AdminRequiredMixin, View):
    template_name = 'core/manage/tournament_list.html'
    paginate_by = 20

    def get(self, request):
        q      = request.GET.get('q', '').strip()
        source = request.GET.get('source', '').strip()
        status = request.GET.get('status', '').strip()

        qs = Tournament.objects.order_by('-created_at')
        if q:
            qs = qs.filter(name__icontains=q)
        if source:
            qs = qs.filter(source=source)
        if status:
            qs = qs.filter(status=status)

        paginator   = Paginator(qs, self.paginate_by)
        page_number = request.GET.get('page', 1)
        page_obj    = paginator.get_page(page_number)

        return render(request, self.template_name, {
            'page_obj':    page_obj,
            'tournaments': page_obj.object_list,
            'paginator':   paginator,
            'is_paginated': paginator.num_pages > 1,
            'q':       q,
            'source_q': source,
            'status_q': status,
            'sources':  list(SOURCE_META.items()),
            'status_choices': [('draft','검수중'), ('ongoing','진행중'), ('finished','종료')],
        })


class TournamentCreateView(AdminRequiredMixin, CreateView):
    model = Tournament
    template_name = 'core/manage/tournament_form.html'
    fields = ['name', 'start_date', 'end_date', 'venue', 'region', 'source',
              'status', 'external_url', 'external_id']
    success_url = reverse_lazy('core:manage_dashboard')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['mode'] = 'create'
        return context


class TournamentUpdateView(AdminRequiredMixin, UpdateView):
    model = Tournament
    template_name = 'core/manage/tournament_form.html'
    fields = ['name', 'start_date', 'end_date', 'venue', 'region', 'source',
              'status', 'external_url', 'external_id']
    success_url = reverse_lazy('core:manage_dashboard')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['mode'] = 'edit'
        return context


class TournamentDeleteView(AdminRequiredMixin, DeleteView):
    model = Tournament
    template_name = 'core/manage/confirm_delete.html'
    success_url = reverse_lazy('core:manage_dashboard')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['item_name'] = self.object.name
        context['cancel_url'] = reverse('core:manage_dashboard')
        return context


class NoticeDeleteView(AdminRequiredMixin, DeleteView):
    model = Notice
    template_name = 'core/manage/confirm_delete.html'
    success_url = reverse_lazy('core:notice_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['item_name'] = self.object.title
        context['cancel_url'] = reverse('core:notice_list')
        return context

        return context