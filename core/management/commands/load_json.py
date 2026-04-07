# core/management/commands/load_json.py
import json
import datetime as dt
from pathlib import Path
from django.core.management.base import BaseCommand
from core.models import Tournament, Source

class Command(BaseCommand):
    help = '수집된 JSONL 파일을 읽어 장고 DB에 적재합니다.'

    def handle(self, *args, **options):
        # 오늘 날짜 기준으로 저장된 파일 찾기 (필요시 파일명 하드코딩 가능)
        today_str = dt.date.today().strftime('%Y%m%d')
        file_path = Path(f"data/raw/baef_{today_str}.jsonl")

        if not file_path.exists():
            self.stdout.write(self.style.ERROR(f"[!] 파일을 찾을 수 없습니다: {file_path}"))
            return

        self.stdout.write(self.style.SUCCESS(f"[*] 데이터 적재 시작: {file_path}"))
        
        success_count = 0
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                
                data = json.loads(line)
                
                # 반자동 적재 로직: start_date가 빈 문자열이거나 null이면 None으로 처리
                s_date = data.get("start_date")
                start_date_obj = None
                if s_date:
                    try:
                        # "YYYY-MM-DD" 형식을 date 객체로 변환
                        y, m, d = map(int, s_date.split("-"))
                        start_date_obj = dt.date(y, m, d)
                    except ValueError:
                        pass

                # 현재 장고 DB 스키마에 맞춰 매핑 (external_url, region 등)
                obj, created = Tournament.objects.update_or_create(
                    external_url=data["original_url"], 
                    defaults={
                        "source": Source.BAEF,
                        "name": data["name"],
                        "start_date": start_date_obj,
                        "end_date": start_date_obj,
                        "region": data.get("region_raw") or data.get("venue") or "",
                    }
                )
                
                status = "신규" if created else "업데이트"
                self.stdout.write(f"[{status}] {obj.name} (날짜: {obj.start_date})")
                success_count += 1

        self.stdout.write(self.style.SUCCESS(f"[v] 총 {success_count}건 DB 적재 완료! 이제 캘린더를 확인하세요."))