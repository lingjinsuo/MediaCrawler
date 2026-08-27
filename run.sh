#!/bin/bash

# ===========================================
# MediaCrawler start script
# Replaces: uv run python -m api.main
# Default port: 8080
# Usage: ./run.sh
# Env: MEDIACRAWLER_PORT (override default port)
# ===========================================

# Config
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="${PROJECT_DIR}/logs/api.log"
SCRIPT_MODULE="api.main"
DEFAULT_PORT=8080
PORT="${MEDIACRAWLER_PORT:-${DEFAULT_PORT}}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Starting MediaCrawler${NC}"
echo -e "${GREEN}========================================${NC}"

# Step 1: switch to project dir
cd "${PROJECT_DIR}" || { echo -e "${RED}Failed to cd to ${PROJECT_DIR}${NC}"; exit 1; }
echo -e "${BLUE}Dir:${NC}$(pwd)"
echo -e "${BLUE}Port:${NC}${PORT}"

# Step 2: check uv environment
echo -e "${YELLOW}[1/4] Checking uv environment...${NC}"
if ! command -v uv >/dev/null 2>&1; then
    echo -e "${RED}uv not found${NC}"
    echo -e "${YELLOW}  Install: curl -LsSf https://astral.sh/uv/install.sh | sh${NC}"
    exit 1
fi
echo -e "${GREEN}uv OK: $(uv --version)${NC}"

# Sync deps if venv exists
if [ -f "pyproject.toml" ] && [ -d ".venv" ]; then
    echo -e "  Syncing deps..."
    uv sync --quiet 2>/dev/null || true
fi

# Step 3: kill old api.main processes
echo -e "${YELLOW}[2/4] Cleaning old api.main processes...${NC}"
PIDS=$(ps aux | grep "api.main" | grep -v grep | awk "{print $2}")
if [ -n "$PIDS" ]; then
    echo -e "  Found old PIDs: $PIDS"
    for PID in $PIDS; do
        kill -9 "$PID" 2>/dev/null && echo -e "  ${GREEN}Killed PID $PID${NC}"
    done
    sleep 1
else
    echo -e "  ${GREEN}No old processes${NC}"
fi

# Step 4: prepare log dir
echo -e "${YELLOW}[3/4] Preparing log dir...${NC}"
LOG_DIR=$(dirname "$LOG_FILE")
if [ ! -d "$LOG_DIR" ]; then
    mkdir -p "$LOG_DIR"
    echo -e "  ${GREEN}Created log dir: $LOG_DIR${NC}"
fi

# Step 5: start service in background
echo -e "${YELLOW}[4/4] Starting service...${NC}"
# PYTHONUNBUFFERED=1 ensures print() / FastAPI log output is flushed immediately
# to logs/api.log instead of being buffered by the uvicorn event loop.
PYTHONUNBUFFERED=1 nohup uv run python -m "${SCRIPT_MODULE}" > "$LOG_FILE" 2>&1 &
NEW_PID=$!
echo -e "${GREEN}Started PID: $NEW_PID${NC}"

sleep 2
if ps -p "$NEW_PID" >/dev/null 2>&1; then
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}MediaCrawler started successfully!${NC}"
    echo -e "${GREEN}  PID: $NEW_PID${NC}"
    echo -e "${GREEN}  Home:    http://127.0.0.1:${PORT}/home${NC}"
    echo -e "${GREEN}  Comment: http://127.0.0.1:${PORT}/comment-push/${NC}"
    echo -e "${GREEN}  API:     http://127.0.0.1:${PORT}/docs${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo -e "${YELLOW}Log:  tail -f $LOG_FILE${NC}"
    echo -e "${YELLOW}Stop: kill $NEW_PID${NC}"
else
    echo -e "${RED}FAILED to start, please check log:${NC}"
    tail -30 "$LOG_FILE" 2>/dev/null
    exit 1
fi
