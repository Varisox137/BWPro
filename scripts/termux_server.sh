#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR="${BWP_REPO_DIR:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"
REMOTE="${BWP_REMOTE:-}"
BRANCH="${BWP_BRANCH:-master}"
HOST="${BWP_HOST:-0.0.0.0}"
PORT="${BWP_PORT:-1037}"
EXPECTED_REMOTE="https://github.com/Varisox137/BWPro.git"

fail() {
    printf '错误：%s\n' "$*" >&2
    exit 1
}

command -v git >/dev/null 2>&1 || fail "未找到 git"
command -v uv >/dev/null 2>&1 || fail "未找到 uv；请先按 https://docs.astral.sh/uv/getting-started/installation/ 安装并配置 PATH"
command -v tee >/dev/null 2>&1 || fail "未找到 tee"
[[ -n "$HOST" ]] || fail "BWP_HOST 不能为空"
[[ "$PORT" =~ ^[0-9]+$ ]] && ((PORT >= 1 && PORT <= 65535)) \
    || fail "BWP_PORT 必须是 1-65535"

cd -- "$REPO_DIR" || fail "无法进入仓库：$REPO_DIR"
[[ "$(git rev-parse --is-inside-work-tree 2>/dev/null)" == "true" ]] \
    || fail "$REPO_DIR 不是 Git 工作区"
[[ "$(git branch --show-current)" == "$BRANCH" ]] \
    || fail "当前分支不是 $BRANCH"
if [[ -z "$REMOTE" ]]; then
    if git remote get-url origin >/dev/null 2>&1; then
        REMOTE=origin
    elif git remote get-url main >/dev/null 2>&1; then
        REMOTE=main
    else
        REMOTE=origin
    fi
fi
REMOTE_URL=$(git remote get-url "$REMOTE" 2>/dev/null) \
    || fail "远端不存在：$REMOTE"
REMOTE_URL=${REMOTE_URL%/}
case "$REMOTE_URL" in
    "$EXPECTED_REMOTE"|"https://github.com/Varisox137/BWPro"|"git@github.com:Varisox137/BWPro.git"|"ssh://git@github.com/Varisox137/BWPro.git")
        ;;
    *)
        fail "远端地址不符合预期：$REMOTE_URL"
        ;;
esac

if [[ -n "$(git status --porcelain --untracked-files=all)" ]]; then
    git status --short
    fail "存在未提交或未跟踪改动；不会自动 stash/reset/clean，请使用干净部署副本"
fi

mkdir -p logs
LOG_FILE="logs/bwpro-launcher-$(date +%Y%m%d-%H%M%S)-$$.log"
exec > >(tee -a "$LOG_FILE") 2>&1

printf '更新 %s/%s，日志：%s\n' "$REMOTE" "$BRANCH" "$LOG_FILE"
git pull --ff-only "$REMOTE" "$BRANCH"
export UV_LINK_MODE="${UV_LINK_MODE:-copy}"
uv sync --locked --managed-python --python 3.14 --no-dev
exec uv run --no-sync python -m server.main --host "$HOST" --port "$PORT" "$@"
