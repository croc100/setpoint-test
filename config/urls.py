#
# Copyright 2026 100 (croc100)
# Licensed under the Apache License, Version 2.0
#
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.config_url if hasattr(admin.site, 'config_url') else admin.site.urls), # 기본 admin

    # django-allauth 소셜 로그인
    path('accounts/', include('allauth.urls')),

    # core 앱의 URL 연결
    path('', include('core.urls')),
]

# 개발 환경에서 Static 파일 서빙 설정
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)