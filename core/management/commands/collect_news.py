"""
네이버 검색 API를 이용한 배드민턴 뉴스 자동 수집
매일 크론으로 실행 → News 테이블을 최신 4개로 교체
"""
import html
import os
import re

import requests
from django.core.management.base import BaseCommand

from core.models import News

NAVER_CLIENT_ID     = os.environ.get('NAVER_CLIENT_ID', '')
NAVER_CLIENT_SECRET = os.environ.get('NAVER_CLIENT_SECRET', '')
API_URL             = 'https://openapi.naver.com/v1/search/news.json'

# 키워드별 (검색어, API display 개수)
# 구체적인 키워드로 관련 없는 기사 자연 차단
KEYWORD_PLAN = [
    ('안세영 배드민턴',        2),   # 한국 에이스
    ('BWF 배드민턴',           2),   # 세계연맹 공식 대회
    ('배드민턴 국가대표 선수', 2),   # 국가대표 소식
    ('배드민턴 운동 건강',     2),   # 건강/라이프
]
MAX_NEWS = 4


def _clean(text: str) -> str:
    """HTML 태그 · 엔티티 제거"""
    text = re.sub(r'<[^>]+>', '', text)
    return html.unescape(text).strip()


class Command(BaseCommand):
    help = '네이버 검색 API로 배드민턴 뉴스 수집 (매일 자동 교체)'

    def handle(self, *args, **options):
        if not NAVER_CLIENT_ID:
            self.stderr.write('NAVER_CLIENT_ID 환경변수가 없습니다.')
            return

        headers = {
            'X-Naver-Client-Id':     NAVER_CLIENT_ID,
            'X-Naver-Client-Secret': NAVER_CLIENT_SECRET,
        }

        collected = []
        seen_urls = set()

        for keyword, display in KEYWORD_PLAN:
            if len(collected) >= MAX_NEWS:
                break
            try:
                res = requests.get(
                    API_URL,
                    headers=headers,
                    params={'query': keyword, 'display': display + 1, 'sort': 'date'},
                    timeout=10,
                )
                res.raise_for_status()
                items = res.json().get('items', [])
                for item in items:
                    url   = item.get('originallink') or item.get('link', '')
                    title = _clean(item.get('title', ''))
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    collected.append({
                        'title':   title,
                        'url':     url,
                        'summary': _clean(item.get('description', '')),
                    })
                    if len(collected) >= MAX_NEWS:
                        break
            except Exception as exc:
                self.stderr.write(f'[{keyword}] 수집 실패: {exc}')

        if not collected:
            self.stdout.write('수집된 뉴스가 없습니다. 기존 데이터 유지.')
            return

        # 기존 뉴스 전체 교체
        News.objects.all().delete()
        for item in collected:
            News.objects.create(**item)

        self.stdout.write(self.style.SUCCESS(
            f'뉴스 {len(collected)}개 저장 완료'
        ))
