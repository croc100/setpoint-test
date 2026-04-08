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
    
    # 사용자가 팔로우하는 선수들 (즐겨찾기 기능)
    following_players = models.ManyToManyField('Player', related_name='followers', blank=True)

    def __str__(self):
        return self.username


# ==========================================
# 2. 선수 및 전적 관련 모델 (핵심 데이터)
# ==========================================

class Player(models.Model):
    """선수 마스터 데이터"""
    name = models.CharField(max_length=100)
    club = models.CharField(max_length=100, db_index=True)
    source = models.CharField(max_length=20, choices=Source.choices) 
    external_uid = models.CharField(max_length=100, unique=True) # 원본 사이트 고유 ID

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
    rank = models.IntegerField(null=True, blank=True, help_text="대회 순위 (예: 1, 2, 3)")
    
    win_count = models.IntegerField(default=0)
    loss_count = models.IntegerField(default=0)
    win_rate = models.FloatField(default=0.0)
    ranking_point = models.IntegerField(default=0)
    
    class Meta:
        unique_together = ('player', 'date')
        ordering = ['-date']

    def __str__(self):
        return f"{self.player.name} - {self.date} 통계"


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
    
    # [수정] 수집기에서 사용하는 필드명 확보
    region = models.CharField(max_length=100, blank=True) 
    region_raw = models.CharField(max_length=255, blank=True, null=True, help_text="수집된 원본 장소 텍스트")
    
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')
    source = models.CharField(max_length=20, choices=Source.choices)
    
    # [수정] 수집기(update_or_create)에서 식별자로 사용하는 필드 추가
    external_id = models.CharField(max_length=100, db_index=True, null=True, blank=True)
    external_url = models.URLField(blank=True, max_length=500) # 원본 링크
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class FeaturedItem(models.Model):
    """메인 화면 '금주의 대회' 노출 관리"""
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
    """공지사항 및 알림"""
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
    """메인 화면 소식 섹션 (외부 뉴스/링크 전용)"""
    title = models.CharField(max_length=255)
    url = models.URLField(blank=True, null=True, max_length=500)
    summary = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "News"

    def __str__(self):
        return self.title