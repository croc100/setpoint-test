#!/bin/bash
# 전체 과거 데이터 백필 스크립트
# - 5개 플랫폼 대회 일정 전체 수집
# - 각 대회 선수 전적 50개씩 배치 수집 (서버 부담 최소화)
#
# 실행: nohup bash scripts/backfill.sh >> logs/backfill.log 2>&1 &

PROJECT_DIR="/home/croc100/setpoint"
PYTHON="${PROJECT_DIR}/.venv/bin/python"
MANAGE="${PROJECT_DIR}/manage.py"
LOG_DIR="${PROJECT_DIR}/logs"

mkdir -p "$LOG_DIR"

echo "=========================================="
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 백필 시작"
echo "=========================================="

cd "$PROJECT_DIR"

# ── STEP 1: 전체 대회 일정 수집 ──
echo ""
echo "[STEP 1] 5개 플랫폼 대회 일정 전체 수집..."
$PYTHON $MANAGE collect_all --no-players
echo "[STEP 1] 완료"

sleep 10

# ── STEP 1.5: 날짜 지난 대회 → finished 상태 갱신 ──
echo ""
echo "[STEP 1.5] 대회 상태 갱신 (end_date 기준)..."
$PYTHON $MANAGE update_tournament_status
echo "[STEP 1.5] 완료"

sleep 5

# ── STEP 2: 전적 배치 수집 (50개씩, 배치 사이 30초 대기) ──
echo ""
echo "[STEP 2] 선수 전적 배치 수집 시작..."

BATCH=50
BATCH_NUM=1

while true; do
    echo ""
    echo "  [배치 ${BATCH_NUM}] $(date '+%H:%M:%S') — ${BATCH}개 처리 중..."
    OUTPUT=$($PYTHON $MANAGE collect_stats --limit $BATCH 2>&1)
    echo "$OUTPUT"

    # 수집 대상 없으면 종료
    if echo "$OUTPUT" | grep -q "수집 대상 없음"; then
        echo ""
        echo "[STEP 2] 모든 전적 수집 완료 (대상 없음)"
        break
    fi

    BATCH_NUM=$((BATCH_NUM + 1))
    echo "  → 30초 대기 중..."
    sleep 30
done

echo ""
echo "=========================================="
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 백필 완료"
echo "=========================================="
