#!/usr/bin/env bash
# enable-agent-skills.sh —— 关联 agent 与本仓库 skills/（项目级 symlink）
#
# 检测策略（双检测，覆盖主流场景）：
#   - 配置目录存在（~/.dsh ~/.claude ~/.cursor ~/.trae ~/.codebuddy ~/.codex）——
#     装了 agent 并用过即有目录，是最可靠的信号；
#   - 或命令可执行（command -v dsh/claude/cursor/trae/codebuddy/codex）——
#     CLI 版 agent 即使目录不在默认位置也能命中。
#   两者皆无 → 该 agent 未检测到（不建；可用 --agents 手动指定）。
# 原理：各 agent 的项目级 skills 目录指向 <repo>/skills（symlink）——DSH 走
#   <repo>/.dsh/skills（项目 root 自动扫描 + watch 热刷新，仓库已跟踪该 symlink，
#   clone 即用无需脚本）；其余 agent 走各自的项目级 skills 目录。只建项目级配置，
#   不碰 agent 全局配置；幂等可重跑。
#
# 用法：
#   bash scripts/enable-agent-skills.sh                      # 自动检测已安装 agent
#   bash scripts/enable-agent-skills.sh --agents claude,codex  # 手动指定
#   bash scripts/enable-agent-skills.sh --all                # 全部建（不管装没装）

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_DIR="$REPO_DIR/skills"

if [ ! -d "$SKILLS_DIR" ]; then
  echo "错误：$SKILLS_DIR 不存在（请确认在 ascend-sleuth 仓库内运行）" >&2
  exit 1
fi

# 建 symlink：目标 <repo>/.<agent>/skills -> ../skills
link_skills() {
  local agent_dir="$1" label="$2"
  local link="$agent_dir/skills"
  if [ -L "$link" ]; then
    echo "[$label] 已配置：$link -> ../skills"
  elif [ -e "$link" ]; then
    echo "[$label] ⚠️  $link 已存在但不是 symlink（真实目录）——跳过，请手动处理"
  else
    mkdir -p "$agent_dir"
    ln -s "../skills" "$link"
    echo "[$label] ✅ 已配置：$link -> ../skills"
  fi
}

# 检测：配置目录存在 或 命令可执行
detected() { [ -d "$HOME/$1" ] || command -v "$2" >/dev/null 2>&1; }

# 六类 agent：label / 配置目录 / 命令 / 仓库内目录
NAMES=("DeepSeek Harness" "Claude Code" "Cursor" "Trae" "CodeBuddy" "Codex")
CONF_DIRS=(".dsh" ".claude" ".cursor" ".trae" ".codebuddy" ".codex")
CMDS=("dsh" "claude" "cursor" "trae" "codebuddy" "codex")

# 参数：默认 auto（自动检测）；--agents 手动指定；--all 全建
MODE="auto"
MANUAL=()
while [ $# -gt 0 ]; do
  case "$1" in
    --agents) MODE="manual"; shift; IFS=',' read -ra MANUAL <<< "$1" ;;
    --all) MODE="all" ;;
    -h|--help) grep -E "^#   bash scripts" "$0" | sed 's/^#   //'; exit 0 ;;
    *) echo "未知参数: $1（--agents <list> / --all / 无参自动检测）" >&2; exit 1 ;;
  esac
  shift
done

configured=0
for i in "${!NAMES[@]}"; do
  name="${NAMES[$i]}"; conf="${CONF_DIRS[$i]}"; cmd="${CMDS[$i]}"
  want=0
  case "$MODE" in
    all) want=1 ;;
    manual)
      for m in "${MANUAL[@]}"; do
        [ "$m" = "$conf" ] || [ "$m" = "${conf#.}" ] && want=1
      done ;;
    auto) detected "$conf" "$cmd" && want=1 ;;
  esac
  [ "$want" -eq 1 ] && { link_skills "$REPO_DIR/$conf" "$name"; configured=$((configured+1)); }
done

if [ "$configured" -eq 0 ]; then
  echo "未检测到已安装 agent（~/.dsh ~/.claude ~/.cursor ~/.trae ~/.codebuddy ~/.codex 或对应命令均无）。"
  echo "确定要用的 agent 不在默认路径 → 手动指定：bash scripts/enable-agent-skills.sh --agents claude"
fi

echo
echo "完成。在仓库目录内启动 agent 即自动发现 skills/（各 agent 项目 roots 扫描）。"
echo "仓库 git pull 更新 SKILL.md 后：DSH 热刷新即时生效；其余 agent 重新加载会话即可。"
