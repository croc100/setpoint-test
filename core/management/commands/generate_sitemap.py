"""
sitemap.xml 정적 파일 생성 커맨드
- 서버 부담 없이 cron으로 하루 1번 실행 → nginx가 정적으로 서빙
- python manage.py generate_sitemap
"""
import os
from datetime import date
from django.core.management.base import BaseCommand
from django.conf import settings
from core.models import Player, Tournament


BASE_URL = 'https://setpoint.kr'
# core/static/sitemap.xml — collectstatic 전에도 nginx가 바로 서빙 가능
OUTPUT_PATH = os.path.join(settings.BASE_DIR, 'core', 'static', 'sitemap.xml')


def url_entry(loc, lastmod=None, changefreq='weekly', priority='0.5'):
    parts = [f'  <url>', f'    <loc>{loc}</loc>']
    if lastmod:
        parts.append(f'    <lastmod>{lastmod}</lastmod>')
    parts += [
        f'    <changefreq>{changefreq}</changefreq>',
        f'    <priority>{priority}</priority>',
        f'  </url>',
    ]
    return '\n'.join(parts)


class Command(BaseCommand):
    help = 'sitemap.xml 정적 파일 생성 (cron 전용)'

    def handle(self, *args, **options):
        today = date.today().isoformat()
        entries = []

        # 고정 페이지
        static_pages = [
            ('/', 'daily', '1.0'),
            ('/players/', 'daily', '0.9'),
            ('/tournaments/', 'daily', '0.9'),
            ('/calendar/', 'weekly', '0.7'),
            ('/ranking/', 'weekly', '0.7'),
        ]
        for path, freq, pri in static_pages:
            entries.append(url_entry(f'{BASE_URL}{path}', today, freq, pri))

        # 선수 상세 페이지
        players = Player.objects.only('id').order_by('id')
        for p in players:
            entries.append(url_entry(
                f'{BASE_URL}/player/{p.id}/',
                today, 'weekly', '0.6',
            ))

        # 대회 상세 페이지
        tournaments = Tournament.objects.only('id', 'start_date').order_by('-start_date')
        for t in tournaments:
            lastmod = t.start_date.isoformat() if t.start_date else today
            entries.append(url_entry(
                f'{BASE_URL}/tournament/{t.id}/',
                lastmod, 'monthly', '0.5',
            ))

        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + '\n'.join(entries)
            + '\n</urlset>\n'
        )

        out = os.path.abspath(OUTPUT_PATH)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, 'w', encoding='utf-8') as f:
            f.write(xml)

        count = len(entries)
        self.stdout.write(self.style.SUCCESS(
            f'sitemap.xml 생성 완료 — {count}개 URL → {out}'
        ))
