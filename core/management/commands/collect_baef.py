from django.core.management.base import BaseCommand
from core.collectors.baef import fetch_baef_from_list

class Command(BaseCommand):
    help = '배프(BAEF) 대회 데이터를 수집하여 DB에 적재합니다.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("[*] 배프(BAEF) 수집을 시작합니다..."))
        
        # 우리가 만든 수집 함수 호출
        fetch_baef_from_list()
        
        self.stdout.write(self.style.SUCCESS("[v] 배프(BAEF) 수집 및 적재 완료!"))