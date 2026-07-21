#!/bin/bash

# ============================================
# MediaCrawler 重启脚本
# 功能：杀掉旧进程 → git pull → 重新启动
# ============================================

# 配置项
PROJECT_DIR="/Users/mac06/code/MediaCrawler"
LOG_FILE="/Users/mac06/data/logs/mc.log"
SCRIPT_PATH="/Users/mac06/code/MediaCrawler/api/main.py"

# 颜色输出（方便查看）
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}开始重启 MediaCrawler 服务${NC}"
echo -e "${GREEN}========================================${NC}"

# ============================================
# 步骤1：杀掉旧进程
# ============================================
echo -e "${YELLOW}[1/4] 正在查找并杀掉旧进程...${NC}"

# 方法1：通过进程名查找并杀掉（推荐）
PIDS=$(ps aux | grep "api.main" | grep -v grep | awk '{print $2}')

# 方法2：如果方法1找不到，尝试通过脚本路径查找
if [ -z "$PIDS" ]; then
    PIDS=$(ps aux | grep "$SCRIPT_PATH" | grep -v grep | awk '{print $2}')
fi

if [ -z "$PIDS" ]; then
    echo -e "${YELLOW}  未找到运行中的进程${NC}"
else
    echo -e "  找到进程 PID: $PIDS"
    for PID in $PIDS; do
        echo -e "  正在杀掉进程 $PID ..."
        kill -9 $PID 2>/dev/null
        if [ $? -eq 0 ]; then
            echo -e "  ${GREEN}✓ 进程 $PID 已杀掉${NC}"
        else
            echo -e "  ${RED}✗ 杀掉进程 $PID 失败${NC}"
        fi
    done
    # 等待进程完全退出
    sleep 2
fi

# ============================================
# 步骤2：切换到项目目录
# ============================================
echo -e "${YELLOW}[2/4] 切换到项目目录...${NC}"
cd "$PROJECT_DIR" || {
    echo -e "${RED}✗ 错误：无法切换到目录 $PROJECT_DIR${NC}"
    exit 1
}
echo -e "${GREEN}✓ 当前目录: $(pwd)${NC}"

# ============================================
# 步骤3：git pull 拉取最新代码
# ============================================
echo -e "${YELLOW}[3/4] 拉取最新代码...${NC}"
git pull
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ git pull 成功${NC}"
else
    echo -e "${RED}✗ git pull 失败，请检查网络或 Git 配置${NC}"
    # 这里不退出，允许继续启动旧版本
    echo -e "${YELLOW}  继续使用当前代码启动${NC}"
fi

# 显示当前 Git 信息
echo -e "  当前分支: $(git branch --show-current)"
echo -e "  最新提交: $(git log -1 --format='%h - %s (%an, %ar)')"

# ============================================
# 步骤4：后台启动服务
# ============================================
echo -e "${YELLOW}[4/4] 启动服务...${NC}"

# 检查日志目录是否存在，不存在则创建
LOG_DIR=$(dirname "$LOG_FILE")
if [ ! -d "$LOG_DIR" ]; then
    echo -e "  创建日志目录: $LOG_DIR"
    mkdir -p "$LOG_DIR"
fi

# 启动服务
nohup uv run python "$SCRIPT_PATH" > "$LOG_FILE" 2>&1 &
NEW_PID=$!

echo -e "${GREEN}✓ 服务已启动，PID: $NEW_PID${NC}"
echo -e "${GREEN}✓ 日志文件: $LOG_FILE${NC}"

# ============================================
# 验证服务是否正常启动
# ============================================
sleep 2
if ps -p $NEW_PID > /dev/null 2>&1; then
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}✓ 服务重启成功！${NC}"
    echo -e "${GREEN}  PID: $NEW_PID${NC}"
    echo -e "${GREEN}  日志: tail -f $LOG_FILE${NC}"
    echo -e "${GREEN}========================================${NC}"
else
    echo -e "${RED}✗ 警告：服务启动后立即退出，请检查日志${NC}"
    echo -e "${RED}  查看日志: tail -f $LOG_FILE${NC}"
    exit 1
fi

# 显示最新几行日志
echo -e "\n${YELLOW}最近日志（最后5行）：${NC}"
tail -5 "$LOG_FILE" 2>/dev/null || echo "  暂无日志"