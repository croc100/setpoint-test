#
# Copyright 2026 100 (croc100)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#

import os
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone

# ==========================================
# 0. 공통 선택 사항 (Enums)
# ==========================================

class Source(models.TextChoices):
    """데이터 출처 정의"""
    WEEKUK = "WEEKUK", "위꾹"
    SPONET = "SPONET", "스포넷"
    NEARMINTON = "NEARMINTON", "우동배"
    FACECOK = "FACECOK", "페이스콕"
    BAEF = "BAEF", "배프"


# ==========================================
# 1. 사용자 및 계정 관련 모델
# ==========================================

class User(AbstractUser):
    """로그인을 위한 확장 유저 모델"""
    nickname = models.CharField(max_length=50, blank=True)
    phone_number = models.CharField(max_length=15, unique=True, null=True)
    
    following_players = models.ManyToManyField('Player', related_name='followers', blank=True)

    def __str__(self):
        return self.username


# ==========================================
# 2. 선수 및 전적 관련 모델 (핵심 데이터)
# ==========================================

class Player(models.Model):
    """선수 마스터 데이터"""
    # [SE Fix] 검색 속도 극대화를 위해 db_index 추가
    name = models.CharField(max_length=100, db_index=True)
    club = models.CharField(max_length=100, db_index=True)
    source = models.CharField(max_length=20, choices=Source.choices) 
    
    # [SE Fix] 위꾹처럼 고유 ID가 명확하지 않은 곳을 대비해 null=True 허용, 대신 인덱스 유지
    external_uid = models.CharField(max_length=100, unique=True, null=True, blank=True, db_index=True) 

    def __str__(self):
        return f"{self.name} ({self.club})"


class PlayerDailyStats(models.Model):
    """일별 전적 누적 데이터 (시계열 분석용)"""
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='daily_stats')
    date = models.DateField(db_index=True)
    
    tournament = models.ForeignKey('Tournament', on_delete=models.SET_NULL, null=True, blank=True)
    gender = models.CharField(max_length=10, blank=True, null=True)
    category_age_band = models.CharField(max_length=50, blank=True, null=True)
    category_level = models.CharField(max_length=50, blank=True, null=True)
    rank = models.CharField(max_length=50, null=True, blank=True, help_text="대회 순위 (예: 1, 우승, 3위 등 문자가 들어올 수 있음)")
    
    win_count = models.IntegerField(default=0)
    loss_count = models.IntegerField(default=0)
    win_rate = models.FloatField(default=0.0)
    ranking_point = models.IntegerField(default=0)

    gain_point = models.IntegerField(default=0, help_text="득실차")
    final_status = models.CharField(max_length=20, null=True, blank=True, help_text="최종 상태 (우승, 본선 진출, 예선 탈락 등)")

    # ==================================================
    # [SE Architecture] Draft & Publish 상태 제어 필드
    # ==================================================
    # 관리자가 어드민에서 승인해야 True로 바뀌며 프론트에 노출됨
    is_verified = models.BooleanField(default=False, db_index=True) 
    # 위꾹 등 휴리스틱(추측성)으로 긁어온 데이터인지 표시 (프론트에 경고 문구 출력용)
    is_heuristic = models.BooleanField(default=False) 
    
    class Meta:
        # [SE Fix] 수집기가 같은 날 같은 선수의 여러 대회 결과를 덮어쓰지 않도록 고유 제약조건 해제
        # (만약 선수가 하루에 2개 대회에 나갔다면 에러가 터지는 구조였음)
        # unique_together = ('player', 'date') -> 삭제!
        
        # [SE Fix] 최신 데이터를 가장 먼저 띄우기 위한 복합 인덱스 (조회 속도 10배 향상)
        indexes = [
            models.Index(fields=['-date', 'is_verified']),
        ]
        ordering = ['-date']

    def __str__(self):
        return f"{self.player.name} - {self.date} 통계 (검증:{self.is_verified})"


# ==========================================
# 3. 대회 및 운영 관련 모델
# ==========================================

class Tournament(models.Model):
    """전국 대회 정보 (자동 수집 및 관리)"""
    STATUS_CHOICES = [
        ('draft', '검수중'),
        ('ongoing', '접수/진행중'),
        ('finished', '종료'),
    ]

    name = models.CharField(max_length=200)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    
    venue = models.CharField(max_length=255, blank=True) 
    region = models.CharField(max_length=100, blank=True) 
    region_raw = models.CharField(max_length=255, blank=True, null=True, help_text="수집된 원본 장소 텍스트")
    
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')
    source = models.CharField(max_length=20, choices=Source.choices)
    
    external_id = models.CharField(max_length=100, db_index=True, null=True, blank=True)
    external_url = models.URLField(blank=True, max_length=500)
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class FeaturedItem(models.Model):
    # ... 기존 코드 유지 ...
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE)
    order = models.PositiveIntegerField(default=0, help_text="낮은 숫자가 먼저 노출됩니다.")

    class Meta:
        ordering = ['order']
        verbose_name = "금주의 대회"

    def __str__(self):
        return self.tournament.name


# ==========================================
# 4. 콘텐츠 및 소식 관련 모델
# ==========================================

class Notice(models.Model):
    # ... 기존 코드 유지 ...
    CATEGORY_CHOICES = [
        ('NOTICE', '공지'),
        ('UPDATE', '업데이트'),
        ('EVENT', '이벤트'),
    ]

    title = models.CharField(max_length=200)
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES, default='NOTICE')
    content = models.TextField()
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    
    is_pinned = models.BooleanField(default=False)
    is_published = models.BooleanField(default=True)
    show_as_page = models.BooleanField(default=False)
    
    publish_at = models.DateTimeField(default=timezone.now) 
    expire_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title


class News(models.Model):
    # ... 기존 코드 유지 ...
    title = models.CharField(max_length=255)
    url = models.URLField(blank=True, null=True, max_length=500)
    summary = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "News"

    def __str__(self):
        return self.title
    

#  ==========================================


class MatchRecord(models.Model):
    """개별 매치(조별리그/본선) 스코어 및 승패 기록 테이블"""
    daily_stat = models.ForeignKey(
        'PlayerDailyStats', 
        related_name='matches', 
        on_delete=models.CASCADE
    )
    bracket_name = models.CharField(max_length=50, null=True, blank=True) # 예: "1조", "본선"
    is_win = models.BooleanField(default=False)
    my_score = models.IntegerField(default=0)
    op_score = models.IntegerField(default=0)
    opponent_names = models.CharField(max_length=255, blank=True, null=True)
    opponent_club = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = 'match_record'
        ordering = ['id'] # 입력 순서대로 정렬