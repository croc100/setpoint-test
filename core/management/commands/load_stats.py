# core/management/commands/load_stats.py
"""
load_stats.py
=============
수집기가 저장한 JSONL 파일을 읽어 DB(PlayerDailyStats, MatchRecord)에 적재합니다.
collect_stats.py 가 수집 완료 후 자동으로 호출하거나, 단독으로도 실행 가능합니다.

[실행 방법]
    python manage.py load_stats                  # 전체 플랫폼
    python manage.py load_stats --source BAEF    # BAEF만 적재
    python manage.py load_stats --source WEEKUK  # WEEKUK만 적재

[BAEF 적재 대상 파일]
    data/raw/players/baef_players_{id}.jsonl
    data/raw/matches/baef_matches_{id}.jsonl
    data/raw/results/results_{id}.jsonl

[WEEKUK 적재 대상 파일]
    data/raw/players/wekkuk_players_{id}.jsonl
    data/raw/winners/wekkuk_winners_{id}.jsonl
"""

import glob
import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone


def _read_jsonl(path) -> list:
    """JSONL 파일을 읽어 리스트로 반환. 파일 없으면 빈 리스트."""
    result = []
    p = Path(path)
    if not p.exists():
        return result
    with open(p, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    result.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return result


class Command(BaseCommand):
    help = "JSONL 수집 파일을 DB에 적재합니다."

    def add_arguments(self, parser):
        parser.add_argument(
            '--source',
            type=str,
            default=None,
            help="특정 플랫폼만 적재 (BAEF / WEEKUK). 생략 시 전체.",
        )

    def handle(self, *args, **options):
        import os
        BASE_DIR = Path(__file__).resolve().parents[4]  # 프로젝트 루트
        raw_dir  = BASE_DIR / "data" / "raw"

        source = (options.get('source') or "").upper() or None

        if source in (None, "BAEF"):
            self.stdout.write("\n[load_stats] BAEF 적재 시작...")
            self._load_baef(raw_dir)

        if source in (None, "WEEKUK"):
            self.stdout.write("\n[load_stats] WEEKUK 적재 시작...")
            self._load_weekuk(raw_dir)

        if source in (None, "SPONET"):
            self.stdout.write("\n[load_stats] SPONET 적재 시작...")
            self._load_sponet(raw_dir)

        if source in (None, "FACECOK"):
            self.stdout.write("\n[load_stats] FACECOK 적재 시작...")
            self._load_facecok(raw_dir)

        self.stdout.write(self.style.SUCCESS("\n[load_stats] 완료"))

    # ──────────────────────────────────────────────────────────
    # BAEF 적재
    # baef_players + baef_matches + results 세 파일을 조인하여
    # PlayerDailyStats + MatchRecord 에 적재
    # ──────────────────────────────────────────────────────────
    def _load_baef(self, raw_dir: Path):
        from core.models import Tournament, Player, PlayerDailyStats, MatchRecord

        player_files = sorted(
            glob.glob(str(raw_dir / "players" / "baef_players_*.jsonl"))
        )
        if not player_files:
            self.stdout.write("  [-] 적재할 BAEF 파일 없음")
            return

        for p_file in player_files:
            # 파일명에서 contest_id 추출: baef_players_215.jsonl → 215
            cid     = Path(p_file).stem.split('_')[-1]
            players = _read_jsonl(p_file)
            matches = _read_jsonl(raw_dir / "matches" / f"baef_matches_{cid}.jsonl")
            results = _read_jsonl(raw_dir / "results" / f"results_{cid}.jsonl")

            if not players:
                continue

            title = players[0].get('contest_title', f'BAEF_{cid}')
            self.stdout.write(f"  [-] {title} (ID:{cid})")

            # ── 랭크 룩업: {선수이름: 순위} ──
            rank_lookup = {}
            for res in results:
                rank_txt = res.get('rank_text', '')
                rank_no  = (1 if '1위' in rank_txt else
                            2 if '2위' in rank_txt else
                            3 if '3위' in rank_txt else None)
                if rank_no:
                    if res.get('p1_name'): rank_lookup[res['p1_name']] = rank_no
                    if res.get('p2_name'): rank_lookup[res['p2_name']] = rank_no

            # ── 매치 룩업: {선수이름: {bracket, wins, losses, gain, matches[]}} ──
            match_lookup = {}
            for m_block in matches:
                bracket = m_block.get('bracket', '')
                detail  = m_block.get('match_detail', {})

                team_info        = detail.get('TEAM_INFO_LIST', [])
                rank_info        = detail.get('RANK_INFO_LIST', [])
                match_detail_list = detail.get('MATCH_DETAIL_LIST', [])

                for team in team_info:
                    team_pk = str(team.get('PK', ''))
                    if not team_pk:
                        continue

                    p1_name = team.get('PLAYER_1_NM')
                    p2_name = team.get('PLAYER_2_NM')

                    wins = losses = gain = 0
                    for r in rank_info:
                        if str(r.get('TEAM_PK')) == team_pk:
                            wins   = r.get('MATCH_WIN_CNT', 0)
                            losses = r.get('MATCH_LOSE_CNT', 0)
                            gain   = r.get('TOTAL_GAIN_POINT', 0)
                            break

                    team_matches = []
                    for md in match_detail_list:
                        scores = md.get('MATCH_DETAIL', {})
                        if team_pk not in scores:
                            continue
                        my_score = scores[team_pk]
                        op_pks   = [k for k in scores if k != team_pk]
                        op_score = scores[op_pks[0]] if op_pks else 0
                        is_win   = (str(md.get('WIN_TEAM_PK')) == team_pk)
                        op_names = (
                            md.get('TEAM_2_PLAYER_NMS')
                            if team_pk in str(md.get('TEAM_1_PLAYER_NMS', ''))
                            else md.get('TEAM_1_PLAYER_NMS')
                        )
                        team_matches.append({
                            'is_win': is_win, 'my_score': my_score,
                            'op_score': op_score, 'op_names': op_names or "상대팀",
                            'bracket': bracket,
                        })

                    stat = {
                        "bracket": bracket, "wins": wins,
                        "losses": losses, "gain": gain,
                        "matches": team_matches,
                    }
                    if p1_name: match_lookup[p1_name] = stat
                    if p2_name: match_lookup[p2_name] = stat

            # ── DB 적재 ──
            try:
                with transaction.atomic():
                    tournament, _ = Tournament.objects.update_or_create(
                        source='BAEF',
                        external_id=cid,
                        defaults={'name': title},
                    )

                    for p_data in players:
                        for i in (1, 2):
                            name = p_data.get(f'player{i}_name')
                            club = p_data.get(f'player{i}_affiliation') or ''
                            if not name:
                                continue

                            uid    = f"BAEF_{name}_{club or 'NONE'}"
                            player, _ = Player.objects.update_or_create(
                                external_uid=uid,
                                defaults={'name': name, 'club': club, 'source': 'BAEF'},
                            )

                            m_data = match_lookup.get(name, {})
                            rank   = rank_lookup.get(name)
                            wins   = m_data.get('wins', 0)
                            losses = m_data.get('losses', 0)

                            # 최종 상태 자동 추론
                            if rank == 1:
                                f_status = "우승"
                            elif rank:
                                f_status = "본선 진출"
                            elif wins > 0 or losses > 0:
                                f_status = "예선 탈락"
                            else:
                                f_status = "결과 없음"

                            stat_obj, _ = PlayerDailyStats.objects.update_or_create(
                                player=player,
                                tournament=tournament,
                                category_age_band=p_data.get('category_full', ''),
                                defaults={
                                    'date':         timezone.now().date(),
                                    'rank':         rank,
                                    'win_count':    wins,
                                    'loss_count':   losses,
                                    'gain_point':   m_data.get('gain', 0),
                                    'final_status': f_status,
                                },
                            )

                            # MatchRecord: 멱등성 보장을 위해 기존 삭제 후 재생성
                            MatchRecord.objects.filter(daily_stat=stat_obj).delete()
                            MatchRecord.objects.bulk_create([
                                MatchRecord(
                                    daily_stat=stat_obj,
                                    bracket_name=m.get('bracket'),
                                    is_win=m.get('is_win'),
                                    my_score=m.get('my_score'),
                                    op_score=m.get('op_score'),
                                    opponent_names=m.get('op_names'),
                                )
                                for m in m_data.get('matches', [])
                            ])

                self.stdout.write(f"  [v] 완료: {title}")

            except Exception as e:
                self.stderr.write(f"  [!] 롤백: {title} ({e})")

    # ──────────────────────────────────────────────────────────
    # WEEKUK 적재
    # wekkuk_players + wekkuk_winners 두 파일 기반
    # winners는 휴리스틱 데이터이므로 is_heuristic=True 마킹
    # ──────────────────────────────────────────────────────────
    def _load_weekuk(self, raw_dir: Path):
        from core.models import Tournament, Player, PlayerDailyStats

        player_files = sorted(
            glob.glob(str(raw_dir / "players" / "wekkuk_players_*.jsonl"))
        )
        if not player_files:
            self.stdout.write("  [-] 적재할 WEEKUK 파일 없음")
            return

        for p_file in player_files:
            cid     = Path(p_file).stem.split('_')[-1]
            players = _read_jsonl(p_file)
            winners = _read_jsonl(raw_dir / "winners" / f"wekkuk_winners_{cid}.jsonl")

            if not players:
                continue

            title = players[0].get('contest_title', f'WEEKUK_{cid}')
            self.stdout.write(f"  [-] {title} (ID:{cid})")

            # ── 입상자 룩업: {선수이름: placement} ──
            # is_heuristic=True 이므로 참고용으로만 사용
            winner_lookup = {}
            for w in winners:
                placement = w.get('placement', '')
                if w.get('player1_name'): winner_lookup[w['player1_name']] = placement
                if w.get('player2_name'): winner_lookup[w['player2_name']] = placement

            try:
                with transaction.atomic():
                    tournament, _ = Tournament.objects.update_or_create(
                        source='WEEKUK',
                        external_id=cid,
                        defaults={'name': title},
                    )

                    for p_data in players:
                        for name_key, club_key in [('player_name', 'affiliation'),
                                                    ('partner_name', 'partner_affiliation')]:
                            name = p_data.get(name_key)
                            club = p_data.get(club_key) or ''
                            if not name:
                                continue

                            uid    = f"WEEKUK_{name}_{club or 'NONE'}"
                            player, _ = Player.objects.update_or_create(
                                external_uid=uid,
                                defaults={'name': name, 'club': club, 'source': 'WEEKUK'},
                            )

                            placement  = winner_lookup.get(name)
                            final_status = placement if placement else "참가"

                            PlayerDailyStats.objects.update_or_create(
                                player=player,
                                tournament=tournament,
                                category_age_band=p_data.get('category_age_band', ''),
                                defaults={
                                    'date':          timezone.now().date(),
                                    'category_level': p_data.get('category_level', ''),
                                    'final_status':   final_status,
                                    'is_heuristic':   True,  # 위꾹 입상자는 휴리스틱
                                },
                            )

                self.stdout.write(f"  [v] 완료: {title}")

            except Exception as e:
                self.stderr.write(f"  [!] 롤백: {title} ({e})")

    # ──────────────────────────────────────────────────────────
    # SPONET 적재
    # sponet_players + sponet_winners 두 파일 기반
    # Tournament name은 collect_all이 이미 설정 → get()으로 조회, 덮어쓰지 않음
    # ──────────────────────────────────────────────────────────
    def _load_sponet(self, raw_dir: Path):
        from core.models import Tournament, Player, PlayerDailyStats

        player_files = sorted(
            glob.glob(str(raw_dir / "players" / "sponet_players_*.jsonl"))
        )
        if not player_files:
            self.stdout.write("  [-] 적재할 SPONET 파일 없음")
            return

        _rank_order = {'우승': 1, '준우승': 2, '3위': 3, '4위': 4}

        for p_file in player_files:
            # 파일명에서 tournament_id 추출: sponet_players_TM_20260215151506.jsonl
            stem = Path(p_file).stem       # "sponet_players_TM_20260215151506"
            cid  = stem[len("sponet_players_"):]
            players = _read_jsonl(p_file)
            winners = _read_jsonl(raw_dir / "winners" / f"sponet_winners_{cid}.jsonl")

            if not players:
                continue

            # Tournament은 collect_all이 이미 생성 (name 덮어쓰지 않음)
            try:
                tournament = Tournament.objects.get(source='SPONET', external_id=cid)
            except Tournament.DoesNotExist:
                tournament = Tournament.objects.create(
                    source='SPONET', external_id=cid, name=cid, status='finished'
                )

            title = tournament.name
            self.stdout.write(f"  [-] {title} (ID:{cid})")

            winner_lookup: dict = {}
            for w in winners:
                placement = (w.get('placement') or '').strip()
                if not placement:
                    continue
                for key in ('player1_name', 'player2_name'):
                    nm = (w.get(key) or '').strip()
                    if nm:
                        existing = winner_lookup.get(nm)
                        if existing is None or \
                                _rank_order.get(placement, 9) < _rank_order.get(existing, 9):
                            winner_lookup[nm] = placement

            try:
                with transaction.atomic():
                    for p_data in players:
                        for name_key, club_key in [('player_name', 'club'),
                                                    ('partner_name', 'partner_club')]:
                            name = (p_data.get(name_key) or '').strip()
                            club = (p_data.get(club_key) or '').strip()
                            if not name:
                                continue

                            uid = f"SPONET_{name}_{club or 'NONE'}"
                            player, _ = Player.objects.update_or_create(
                                external_uid=uid,
                                defaults={'name': name, 'club': club, 'source': 'SPONET'},
                            )

                            pmt          = winner_lookup.get(name)
                            final_status = pmt if pmt else "참가"

                            PlayerDailyStats.objects.update_or_create(
                                player=player,
                                tournament=tournament,
                                category_age_band=p_data.get('category_age_band', ''),
                                defaults={
                                    'date':           timezone.now().date(),
                                    'category_level': p_data.get('category_level', ''),
                                    'final_status':   final_status,
                                    'is_heuristic':   False,  # 실제 대진 데이터
                                },
                            )

                self.stdout.write(f"  [v] SPONET 완료: {title}")

            except Exception as exc:
                self.stderr.write(f"  [!] 롤백: {title} ({exc})")

    # ──────────────────────────────────────────────────────────
    # FACECOK 적재
    # facecok_players + facecok_winners 두 파일 기반
    # ──────────────────────────────────────────────────────────
    def _load_facecok(self, raw_dir: Path):
        from core.models import Tournament, Player, PlayerDailyStats

        player_files = sorted(
            glob.glob(str(raw_dir / "players" / "facecok_players_*.jsonl"))
        )
        if not player_files:
            self.stdout.write("  [-] 적재할 FACECOK 파일 없음")
            return

        _rank_order = {'우승': 1, '준우승': 2, '3위': 3, '4위': 4}

        for p_file in player_files:
            cid     = Path(p_file).stem.split('_')[-1]
            players = _read_jsonl(p_file)
            winners = _read_jsonl(raw_dir / "winners" / f"facecok_winners_{cid}.jsonl")

            if not players:
                continue

            try:
                tournament = Tournament.objects.get(source='FACECOK', external_id=cid)
            except Tournament.DoesNotExist:
                tournament = Tournament.objects.create(
                    source='FACECOK', external_id=cid, name=cid, status='finished'
                )

            title = tournament.name
            self.stdout.write(f"  [-] {title} (ID:{cid})")

            winner_lookup: dict = {}
            for w in winners:
                placement = (w.get('placement') or '').strip()
                if not placement:
                    continue
                for key in ('player1_name', 'player2_name'):
                    nm = (w.get(key) or '').strip()
                    if nm:
                        existing = winner_lookup.get(nm)
                        if existing is None or \
                                _rank_order.get(placement, 9) < _rank_order.get(existing, 9):
                            winner_lookup[nm] = placement

            try:
                with transaction.atomic():
                    for p_data in players:
                        for name_key, club_key in [('player_name', 'club'),
                                                    ('partner_name', 'partner_club')]:
                            name = (p_data.get(name_key) or '').strip()
                            club = (p_data.get(club_key) or '').strip()
                            if not name:
                                continue

                            uid = f"FACECOK_{name}_{club or 'NONE'}"
                            player, _ = Player.objects.update_or_create(
                                external_uid=uid,
                                defaults={'name': name, 'club': club, 'source': 'FACECOK'},
                            )

                            pmt          = winner_lookup.get(name)
                            final_status = pmt if pmt else "참가"

                            PlayerDailyStats.objects.update_or_create(
                                player=player,
                                tournament=tournament,
                                category_age_band=p_data.get('category_age_band', ''),
                                defaults={
                                    'date':           timezone.now().date(),
                                    'category_level': p_data.get('category_level', ''),
                                    'final_status':   final_status,
                                    'is_heuristic':   True,  # HTML 파싱 기반
                                },
                            )

                self.stdout.write(f"  [v] FACECOK 완료: {title}")

            except Exception as exc:
                self.stderr.write(f"  [!] 롤백: {title} ({exc})")
