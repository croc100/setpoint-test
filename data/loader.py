import os
import sys
import json
import glob
from pathlib import Path
from django.utils import timezone

# ---------------------------------------------------------
# [1] 장고 환경(Environment) 완벽 분리 및 초기화
# ---------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
django.setup()

from django.db import transaction
# MatchRecord 모델 임포트 추가 (models.py에 선언 필수)
from core.models import Tournament, Player, PlayerDailyStats, Source, MatchRecord

# ---------------------------------------------------------
# [Helper] JSONL 파일 읽기 유틸리티
# ---------------------------------------------------------
def read_jsonl(filepath):
    data = []
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    data.append(json.loads(line.strip()))
    return data

# ---------------------------------------------------------
# [2] 기존 데이터 적재 로직 (Legacy 지원)
# ---------------------------------------------------------
def load_tournaments():
    """대회 정보 적재: 모든 JSON 파일을 읽어 최신 정보로 Update/Insert"""
    file_pattern = os.path.join(BASE_DIR, "data", "raw", "tournaments", "*.json")
    files = sorted(glob.glob(file_pattern))
    
    if not files:
        print("[!] 적재할 대회 JSON 파일이 없습니다.")
        return

    print(f"[*] 총 {len(files)}개의 대회 JSON 파일을 처리합니다.")
    for file_path in files:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        with transaction.atomic():
            for item in data:
                end_date = item.get('end_date') or item.get('start_date')
                source_val = item.get('source', 'UNKNOWN')
                
                Tournament.objects.update_or_create(
                    external_id=item['external_id'],
                    defaults={
                        "name": item['name'],
                        "start_date": item.get('start_date'),
                        "end_date": end_date,
                        "region_raw": item.get('region_raw', ''),
                        "venue": item.get('venue', ''),
                        "external_url": item.get('external_url', ''),
                        "source": getattr(Source, source_val, source_val)
                    }
                )
        print(f"  [+] 완료: {os.path.basename(file_path)}")

def load_player_stats():
    """선수 전적 정보 적재: 참조 무결성 방어 및 트랜잭션 적용"""
    file_pattern = os.path.join(BASE_DIR, "data", "raw", "players", "*.json")
    files = sorted(glob.glob(file_pattern))
    
    # [SE Fix] 디버그 파일(debug_detail_*.json) 등 잘못된 타겟 제외
    valid_files = [f for f in files if "debug_" not in os.path.basename(f)]
    
    if not valid_files:
        print("[!] 적재할 선수 전적 JSON 파일이 없습니다.")
        return

    print(f"[*] 총 {len(valid_files)}개의 선수 전적 JSON 파일을 처리합니다.")
    for file_path in valid_files:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # [SE Fix] 데이터가 리스트 형태가 아니면(단일 딕셔너리 등) 패스
        if not isinstance(data, list):
            print(f"  [-] 스킵: {os.path.basename(file_path)} (리스트 포맷이 아님)")
            continue

        with transaction.atomic():
            for item in data:
                tournament_obj = Tournament.objects.filter(external_id=item['tournament_external_id']).first()
                if not tournament_obj:
                    continue 

                player, _ = Player.objects.get_or_create(
                    external_uid=item['external_uid'],
                    defaults={
                        "name": item['player_name'],
                        "club": item.get('club', ''),
                        "source": item.get('source', 'BAEF')
                    }
                )

                PlayerDailyStats.objects.update_or_create(
                    player=player,
                    date=item['date'],
                    tournament=tournament_obj, 
                    defaults={
                        "gender": item['stats'].get('gender', ''),
                        "category_age_band": item['stats'].get('age_band', ''),
                        "category_level": item['stats'].get('level', ''),
                        "rank": item['stats'].get('rank'),
                        "win_count": item['stats'].get('win_count', 0),
                        "loss_count": item['stats'].get('loss_count', 0)
                    }
                )
        print(f"  [+] 완료: {os.path.basename(file_path)}")

# ---------------------------------------------------------
# [3] 신규 BAEF 통합 데이터 파이프라인 (Phase 3)
# ---------------------------------------------------------
def load_baef_pipeline():
    """BAEF 수집기에서 생성된 Players, Matches, Results 3종 JSONL 조인 및 적재"""
    raw_dir = Path(BASE_DIR) / "data" / "raw"
    player_files = sorted(glob.glob(str(raw_dir / "players" / "baef_players_*.jsonl")))
    
    if not player_files:
        print("[!] 적재할 BAEF JSONL 파일이 없습니다.")
        return

    print(f"[*] 총 {len(player_files)}개 대회의 BAEF 데이터를 통합 적재합니다.")

    for p_file in player_files:
        # 파일명에서 대회 ID(contest_id) 추출
        cid = os.path.basename(p_file).split('_')[-1].split('.')[0]
        
        players = read_jsonl(p_file)
        matches = read_jsonl(raw_dir / "matches" / f"baef_matches_{cid}.jsonl")
        results = read_jsonl(raw_dir / "results" / f"results_{cid}.jsonl")
        
        if not players:
            continue
            
        title = players[0].get('contest_title', f'BAEF_Contest_{cid}')
        print(f"  [-] 처리 중: {title} (ID: {cid})")

        # 1. 랭크(입상) 룩업 빌드
        rank_lookup = {}
        for res in results:
            rank_txt = res.get('rank_text', '')
            rank_no = 1 if '1위' in rank_txt else 2 if '2위' in rank_txt else 3 if '3위' in rank_txt else None
            if rank_no:
                if res.get('p1_name'): rank_lookup[res['p1_name']] = rank_no
                if res.get('p2_name'): rank_lookup[res['p2_name']] = rank_no

        # 2. 상세 매치 및 승패 룩업 빌드
        match_lookup = {}
        for m_block in matches:
            bracket = m_block.get('bracket', '')
            detail = m_block.get('match_detail', {})
            
            team_info = detail.get('TEAM_INFO_LIST', [])
            rank_info = detail.get('RANK_INFO_LIST', [])
            match_detail_list = detail.get('MATCH_DETAIL_LIST', [])

            for team in team_info:
                team_pk = str(team.get('PK', ''))
                if not team_pk: continue

                p1_name, p2_name = team.get('PLAYER_1_NM'), team.get('PLAYER_2_NM')
                
                wins, losses, gain = 0, 0, 0
                for r in rank_info:
                    if str(r.get('TEAM_PK')) == team_pk:
                        wins, losses, gain = r.get('MATCH_WIN_CNT', 0), r.get('MATCH_LOSE_CNT', 0), r.get('TOTAL_GAIN_POINT', 0)
                        break
                
                team_matches = []
                for md in match_detail_list:
                    scores = md.get('MATCH_DETAIL', {})
                    if team_pk in scores:
                        my_score = scores[team_pk]
                        op_pk = [k for k in scores.keys() if k != team_pk]
                        op_score = scores[op_pk[0]] if op_pk else 0
                        is_win = (str(md.get('WIN_TEAM_PK')) == team_pk)
                        
                        op_names = md.get('TEAM_1_PLAYER_NMS') if str(md.get('WIN_TEAM_PK')) != team_pk else md.get('TEAM_2_PLAYER_NMS')
                        if not op_names: 
                            op_names = md.get('TEAM_2_PLAYER_NMS') if team_pk in str(md.get('TEAM_1_PLAYER_NMS', '')) else md.get('TEAM_1_PLAYER_NMS')
                            
                        team_matches.append({
                            'is_win': is_win, 'my_score': my_score, 'op_score': op_score, 
                            'op_names': op_names or "상대팀", 'bracket': bracket
                        })

                stat_data = {"bracket": bracket, "wins": wins, "losses": losses, "gain": gain, "matches": team_matches}
                if p1_name: match_lookup[p1_name] = stat_data
                if p2_name: match_lookup[p2_name] = stat_data

        # 3. DB 적재 (트랜잭션으로 묶어 원자성 보장)
        try:
            with transaction.atomic():
                # 대회 생성
                tournament, _ = Tournament.objects.update_or_create(
                    external_id=cid,
                    defaults={'name': title, 'source': 'BAEF'} # 상세 날짜는 디버그 JSON에서 파싱해 넣을 수 있음
                )

                for p_data in players:
                    for i in [1, 2]:
                        p_name = p_data.get(f'player{i}_name')
                        p_club = p_data.get(f'player{i}_affiliation')
                        if not p_name: continue

                        # 식별자: BAEF_이름_클럽 (동명이인 처리 최소 방어선)
                        uid = f"BAEF_{p_name}_{p_club or 'NONE'}"
                        player, _ = Player.objects.update_or_create(
                            external_uid=uid,
                            defaults={'name': p_name, 'club': p_club, 'source': 'BAEF'}
                        )

                        m_data = match_lookup.get(p_name, {})
                        rank = rank_lookup.get(p_name)
                        
                        wins = m_data.get('wins', 0)
                        losses = m_data.get('losses', 0)
                        
                        # 자동 상태 추론
                        f_status = "결과 없음"
                        if rank == 1: f_status = "우승"
                        elif rank: f_status = "본선 진출"
                        elif wins > 0 or losses > 0: f_status = "예선 탈락"

                        # PlayerDailyStats 적재
                        stat_obj, _ = PlayerDailyStats.objects.update_or_create(
                            player=player,
                            tournament=tournament,
                            category_age_band=p_data.get('category_full', ''),
                            defaults={
                                'date': timezone.now().date(), # 뷰에서 사용할 기준일
                                'rank': rank,
                                'win_count': wins,
                                'loss_count': losses,
                                'gain_point': m_data.get('gain', 0),
                                'final_status': f_status
                            }
                        )

                        # 기존 매치 기록 초기화 후 재생성 (멱등성 보장)
                        MatchRecord.objects.filter(daily_stat=stat_obj).delete()
                        matches_to_create = [
                            MatchRecord(
                                daily_stat=stat_obj, bracket_name=m.get('bracket'),
                                is_win=m.get('is_win'), my_score=m.get('my_score'),
                                op_score=m.get('op_score'), opponent_names=m.get('op_names')
                            ) for m in m_data.get('matches', [])
                        ]
                        if matches_to_create:
                            MatchRecord.objects.bulk_create(matches_to_create)

            print(f"  [+] 완료: {title} (DB 적재 성공)")
        except Exception as e:
            print(f"  [!] 오류: {title} DB 적재 중 롤백됨. ({e})")


# ---------------------------------------------------------
# [4] 메인 실행 오케스트레이터
# ---------------------------------------------------------
if __name__ == "__main__":
    print("="*50)
    print("🚀 데이터베이스 적재(Loader) 파이프라인 가동")
    print("="*50)
    
    print("\n[Phase 1] 기존 대회 정보(Tournament .json) 로딩...")
    load_tournaments()
    
    print("\n[Phase 2] 기존 선수 전적(Player Stats .json) 로딩...")
    load_player_stats()
    
    print("\n[Phase 3] 신규 BAEF 통합 데이터(Players/Matches/Results .jsonl) 조인 및 로딩...")
    load_baef_pipeline()
    
    print("\n" + "="*50)
    print("✅ 모든 데이터베이스 적재가 안전하게 완료되었습니다.")
    print("="*50)