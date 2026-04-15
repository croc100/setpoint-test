import json
import glob
from pathlib import Path

def search_player_history(player_name):
    # 1. 수집된 모든 BAEF 데이터 파일 경로 가져오기
    file_path = "data/raw/players/baef_players_*.jsonl"
    files = glob.glob(file_path)
    
    if not files:
        print(f"[!] '{file_path}' 경로에 데이터 파일이 없습니다.")
        return

    print(f"[*] '{player_name}' 선수의 전적 통합 검색 중...\n")
    
    results = []
    
    # 2. 각 파일을 순회하며 데이터 검색
    for file in files:
        with open(file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    record = json.loads(line)
                    # p1 혹은 p2 이름이 일치하는지 확인
                    if record.get("player1_name") == player_name or record.get("player2_name") == player_name:
                        results.append(record)
                except json.JSONDecodeError:
                    continue

    # 3. 결과 출력
    if not results:
        print(f"[-] '{player_name}' 선수의 기록을 찾을 수 없습니다.")
        return

    print(f"[v] 총 {len(results)}건의 대회 참가 기록을 발견했습니다.")
    print("-" * 80)
    print(f"{'대회명':<30} | {'종목':<10} | {'파트너':<8} | {'소속'}")
    print("-" * 80)

    for res in results:
        # 파트너 결정
        partner = res['player2_name'] if res['player1_name'] == player_name else res['player1_name']
        affiliation = res['player1_affiliation'] if res['player1_name'] == player_name else res['player2_affiliation']
        
        title = res['contest_title'][:28] # 출력 정렬을 위한 슬라이싱
        category = res['category_full']
        
        print(f"{title:<30} | {category:<10} | {partner:<8} | {affiliation}")

if __name__ == "__main__":
    import sys
    
    # 터미널 인자로 이름을 받음 (예: python search_player.py 홍길동)
    target_name = sys.argv[1] if len(sys.argv) > 1 else input("검색할 선수 이름을 입력하세요: ")
    search_player_history(target_name)