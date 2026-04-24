#!/bin/bash
# setpoint 자동 데이터 갱신 스크립트
# 서버 crontab에 등록하여 사용
#
# 설정 방법:
#   crontab -e
#   0 3 * * * /home/croc100/setpoint/scripts/cron_collect.sh >> /home/croc100/setpoint/logs/cron.log 2>&1

set -e

PROJECT_DIR="/home/croc100/setpoint"
PYTHON="${PROJECT_DIR}/.venv/bin/python"
MANAGE="${PROJECT_DIR}/manage.py"
LOG_DIR="${PROJECT_DIR}/logs"
DATE=$(date '+%Y-%m-%d %H:%M:%S')

mkdir -p "$LOG_DIR"

echo "=========================================="
echo "[$DATE] setpoint 자동 수집 시작"
echo "=========================================="

cd "$PROJECT_DIR"

# 1. 대회 일정 수집 (전 플랫폼 — incremental: 기존 ID skip, 전체 페이지 조회)
echo "[1/4] 대회 일정 수집..."
$PYTHON $MANAGE collect_all --no-players
echo "      완료"

# 2. 대회 상태 자동 갱신 (end_date 지난 대회 → finished)
echo "[2/5] 대회 상태 갱신..."
$PYTHON $MANAGE update_tournament_status
echo "      완료"

# 3. 미수집 대회 전적 수집 (최대 50개/회)
echo "[3/5] 선수 전적 수집..."
$PYTHON $MANAGE collect_stats --limit 50
echo "      완료"

# 4. 배드민턴 뉴스 수집 (네이버 검색 API)
echo "[4/5] 뉴스 수집..."
$PYTHON $MANAGE collect_news
echo "      완료"

# 5. sitemap.xml 재생성
echo "[5/5] sitemap.xml 생성..."
$PYTHON $MANAGE generate_sitemap
echo "      완료"

echo "[$DATE] 자동 수집 완료"
echo ""
