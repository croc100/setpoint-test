# core/collectors/status_facecok.py
"""
status_facecok.py
=================
페이스콕(FACECOK) 플랫폼 전적 수집기.

현재 상태: 미구현 (스텁)
이유: facecock.co.kr의 결과 데이터가 JavaScript로 동적 로드됨.
     정적 HTML 파싱으로는 선수 이름/성적 수집 불가.
     추후 Playwright(헤드리스 브라우저) 기반으로 구현 예정.

[인터페이스] collect_stats.py 호환
    run_facecok_stats_hunter(contest_ids: list[str]) -> list[str]
"""

from typing import List


def run_facecok_stats_hunter(contest_ids: List[str], sleep: float = 0.3) -> List[str]:
    """
    페이스콕 전적 수집 (미구현).
    JavaScript 렌더링 필요 → Playwright 도입 후 구현 예정.
    빈 리스트 반환 → collect_stats가 마킹 스킵 → 다음 실행에 재시도.
    """
    print(f"  [FACECOK] 수집기 미구현 — {len(contest_ids)}개 스킵")
    return []  # 성공 ID 없음 → is_stats_fetched 마킹 안 됨
