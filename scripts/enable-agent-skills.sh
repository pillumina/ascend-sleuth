#!/usr/bin/env bash
# enable-agent-skills.sh —— 自动关联当前 agent 与本仓库 skills/
#
# 原理：各 agent 的项目级 skills 目录指向 <repo>/skills（symlink）——
#   - DeepSeek Harness: <repo>/.dsh/skills（DSH 项目 roots 自动扫描 + watch 热刷新，
#     git pull 更新 SKILL.md 后 catalog 即时生效，无需重装/重启）
#   - Claude Code: <repo>/.claude/skills（项目级 skills）
#   - Cursor: <repo>/.cursor/skills
#   - Trae: <repo>/.trae/skills（及 .trae-cn）
# 只建项目级配置，不碰 agent 全局配置；幂等（已存在则跳过/重建）；clone 后跑一次即可。
#
# 用法：bash scripts/enable-agent-skills.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_DIR="$REPO_DIR/skills"

if [ ! -d "$SKILLS_DIR" ]; then
  echo "错误：$SKILLS_DIR 不存在（请确认在 ascend-sleuth 仓库内运行）" >&2
  exit 1
fi

# 建 symlink：目标 <repo>/.<agent>/skills -> ../skills
link_skills() {
  local agent_dir="$1"   # 如 "$REPO_DIR/.claude"
  local label="$2"
  local link="$agent_dir/skills"
  if [ -L "$link" ]; then
    echo "[$label] 已配置（symlink 已存在）：$link -> ../skills"
  elif [ -e "$link" ]; then
    echo "[$label] ⚠️  $link 已存在但不是 symlink（真实目录）——跳过，请手动处理"
  else
    mkdir -p "$agent_dir"
    ln -s "../skills" "$link"
    echo "[$label] ✅ 已配置：$link -> ../skills"
  fi
}

configured=0

# 检测当前环境里装了哪些 agent（都配置，不互斥；项目级无副作用）
[ -d "$HOME/.dsh" ] && { link_skills "$REPO_DIR/.dsh" "DeepSeek Harness"; configured=$((configured+1)); }
[ -d "$HOME/.claude" ] && { link_skills "$REPO_DIR/.claude" "Claude Code"; configured=$((configured+1)); }
[ -d "$HOME/.cursor" ] && { link_skills "$REPO_DIR/.cursor" "Cursor"; configured=$((configured+1)); }
[ -d "$HOME/.trae" ] || [ -d "$HOME/.trae-cn" ] && { link_skills "$REPO_DIR/.trae" "Trae"; configured=$((configured+1)); }

if [ "$configured" -eq 0 ]; then
  echo "未检测到常见 agent 配置目录（~/.dsh ~/.claude ~/.cursor ~/.trae）——请按 README「安装」节手动配置，或先安装目标 agent。"
fi

echo
echo "完成。在仓库目录内启动 agent 即自动发现 skills/（各 agent 项目 roots 扫描）。"
echo "仓库 git pull 更新 SKILL.md 后：DSH 热刷新即时生效；其余 agent 重新加载会话即可。"
echo "这些 symlink 目录（.dsh/.claude/.cursor/.trae）已被 .gitignore 排除，不入版本库。"
