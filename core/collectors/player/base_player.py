from __future__ import annotations

import importlib
from typing import List

# source → 선수 전적 수집 모듈 매핑
_SOURCE_MODULE_MAP = {
    "BAEF":       "core.collectors.player.baef_player",
    "WEEKUK":     "core.collectors.player.wekkuk_player",
    "SPONET":     "core.collectors.player.sponet_player",
    "FACECOK":    "core.collectors.player.facecock_player",
    "NEARMINTON": "core.collectors.player.nearminton_player",
}


def collect_player_stats_for_tournament(tournament: dict) -> List[dict]:
    """
    대회 정보를 받아 해당 플랫폼의 선수 전적을 수집한다.

    tournament 필수 키:
        external_id  - 플랫폼 내부 대회 ID
        source       - "BAEF" | "WEEKUK" | "SPONET" | "FACECOK" | "NEARMINTON"
        name         - 대회명
        start_date   - "YYYY-MM-DD"
        external_url - 원본 URL

    반환: List[player_stat_dict]
        player_name, player_club, gender, category_age_band, category_level,
        rank, final_status, win_count, loss_count, gain_point, is_heuristic,
        matches (List[match_dict])
    """
    source = tournament.get("source", "")
    module_path = _SOURCE_MODULE_MAP.get(source)

    if not module_path:
        print(f"  [!] 알 수 없는 source: {source}")
        return []

    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError:
        print(f"  [!] 선수 수집 모듈을 찾을 수 없음: {module_path}")
        return []

    if not hasattr(module, "collect_player_stats"):
        print(f"  [!] {module_path}에 collect_player_stats 함수가 없습니다.")
        return []

    return module.collect_player_stats(tournament)
