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

# 1. 대회 일정 수집 (전 플랫폼)
echo "[1/3] 대회 일정 수집..."
$PYTHON $MANAGE collect_all --no-players
echo "      완료"

# 2. 미수집 대회 전적 수집 (최근 30개만)
echo "[2/3] 선수 전적 수집..."
$PYTHON $MANAGE collect_stats --limit 30
echo "      완료"

# 3. 배드민턴 뉴스 수집 (네이버 검색 API)
echo "[3/3] 뉴스 수집..."
$PYTHON $MANAGE collect_news
echo "      완료"

echo "[$DATE] 자동 수집 완료"
echo ""
