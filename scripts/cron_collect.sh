#!/bin/bash
# setpoint 자동 데이터 갱신 스크립트
# 서버 crontab에 등록하여 사용
#
# 설정 방법:
#   crontab -e
#   0 3 * * * /home/croc100/setpoint/scripts/cron_collect.sh >> /home/croc100/setpoint/logs/cron.log 2>&1

# set -e 제거: 개별 단계 실패 시 다음 단계는 계속 진행
PROJECT_DIR="/home/croc100/setpoint"
PYTHON="${PROJECT_DIR}/.venv/bin/python"
MANAGE="${PROJECT_DIR}/manage.py"
LOG_DIR="${PROJECT_DIR}/logs"
DATE=$(date '+%Y-%m-%d %H:%M:%S')

mkdir -p "$LOG_DIR"

# 단계별 실행 함수 — 실패해도 전체 스크립트 중단 안 함
run_step() {
    local step="$1"
    local desc="$2"
    shift 2
    echo ""
    echo "[${step}/5] ${desc}..."
    if "$@"; then
        echo "      [완료]"
    else
        echo "      [!] 실패 (exit $?) — 다음 단계 계속"
    fi
}

echo "=========================================="
echo "[$DATE] setpoint 자동 수집 시작"
echo "=========================================="

cd "$PROJECT_DIR"

run_step 1 "대회 일정 수집 (전 플랫폼, incremental)" \
    $PYTHON $MANAGE collect_all --no-players

run_step 2 "대회 상태 갱신 (end_date 지난 대회 → finished)" \
    $PYTHON $MANAGE update_tournament_status

run_step 3 "미수집 대회 전적 수집 (최대 300개, sleep=0.5s)" \
    $PYTHON $MANAGE collect_stats --limit 300 --sleep 0.5

run_step 4 "배드민턴 뉴스 수집 (네이버 검색 API)" \
    $PYTHON $MANAGE collect_news

run_step 5 "선수 급수(level) 소급 갱신" \
    $PYTHON $MANAGE backfill_player_level

run_step 6 "sitemap.xml 재생성" \
    $PYTHON $MANAGE generate_sitemap

DATE_END=$(date '+%Y-%m-%d %H:%M:%S')
echo ""
echo "=========================================="
echo "[$DATE_END] 자동 수집 완료"
echo "=========================================="
echo ""
