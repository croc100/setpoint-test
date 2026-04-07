#
# Copyright 2026 100 (croc100)
# SETPOINT Admin Dashboard Configuration
#
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from .models import User, Notice, Tournament, Player, PlayerDailyStats, News, FeaturedItem

# ==========================================
# 1. 유저 (User) 관리
# ==========================================
@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('추가 정보 (Setpoint)', {'fields': ('nickname', 'phone_number', 'following_players')}),
    )
    list_display = ('username', 'email', 'nickname', 'is_staff')

# ==========================================
# 2. 공지사항 (Notice) 관리
# ==========================================
@admin.register(Notice)
class NoticeAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'author', 'is_published', 'is_pinned', 'publish_at') 
    list_editable = ('is_published', 'is_pinned') 
    search_fields = ('title', 'content')
    list_filter = ('category', 'is_published', 'is_pinned')

# ==========================================
# [추가] 결측치(날짜 누락) 탐색용 커스텀 필터
# ==========================================
class MissingDateFilter(admin.SimpleListFilter):
    title = '날짜 입력 필요 (포스터)'
    parameter_name = 'missing_date'

    def lookups(self, request, model_admin):
        return (('yes', '날짜 누락됨 (수작업 필요)'), ('no', '날짜 있음 (완료)'))

    def queryset(self, request, queryset):
        if self.value() == 'yes':
            return queryset.filter(start_date__isnull=True)
        if self.value() == 'no':
            return queryset.filter(start_date__isnull=False)
        return queryset

# ==========================================
# 3. 대회 (Tournament) 관리 (휴먼 인 더 루프 최적화)
# ==========================================
@admin.register(Tournament)
class TournamentAdmin(admin.ModelAdmin):
    # 리스트에 표시할 컬럼 (날짜와 지역, 원본 링크 추가)
    list_display = ('name', 'start_date', 'end_date', 'region', 'status_badge', 'source', 'original_link')
    
    # [핵심] 리스트 화면에서 상세페이지 진입 없이 바로 날짜/장소 타이핑 가능
    list_editable = ('start_date', 'end_date', 'region')
    
    # [핵심] 날짜 누락 필터 추가
    list_filter = (MissingDateFilter, 'status', 'region', 'source')
    search_fields = ('name', 'region')
    
    def status_badge(self, obj):
        colors = {'draft': 'gray', 'ongoing': 'blue', 'finished': 'red'}
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, 'black'),
            obj.get_status_display()
        )
    status_badge.short_description = "진행 상태"

    def original_link(self, obj):
        if obj.external_url:
            return format_html(
                '<a href="{}" target="_blank" style="background-color: #4CAF50; color: white; padding: 3px 8px; border-radius: 4px; text-decoration: none; font-size: 12px;">공문 확인</a>',
                obj.external_url
            )
        return "-"
    original_link.short_description = "원본 포스터"

# ==========================================
# 4. 선수 및 전적 (Player & Stats) 관리
# ==========================================
class StatsInline(admin.TabularInline):
    model = PlayerDailyStats
    extra = 0
    can_delete = True
    fields = ('date', 'tournament', 'category_level', 'rank', 'win_rate', 'ranking_point')
    readonly_fields = ('date',)

@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ('name', 'club', 'get_recent_win_rate', 'source')
    search_fields = ('name', 'external_uid', 'club')
    list_filter = ('source',)
    inlines = [StatsInline]
    
    def get_recent_win_rate(self, obj):
        latest = obj.daily_stats.order_by('-date').first()
        return f"{latest.win_rate}%" if latest else "-"
    get_recent_win_rate.short_description = "최근 승률"

@admin.register(PlayerDailyStats)
class PlayerDailyStatsAdmin(admin.ModelAdmin):
    list_display = ('player', 'date', 'tournament', 'rank', 'win_count', 'loss_count')
    list_filter = ('date', 'category_level')
    search_fields = ('player__name', 'tournament__name')

# ==========================================
# 5. 기타 모델 등록
# ==========================================
admin.site.register(FeaturedItem)
admin.site.register(News)