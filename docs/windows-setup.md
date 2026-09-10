# Windows 环境：让 agent 发现 skills

本仓通过 `.dsh/skills → ../skills` 的**相对 symlink** 让 agent 发现 skills，这个 symlink 是 git 跟踪的条目（index mode `120000`）。Git for Windows 默认 `core.symlinks=false`，**clone / worktree 都不会还原 symlink**，于是 `.dsh/skills` 落成一个普通文本文件（内容为 `../skills`）。agent 把它当文件读，发现不了 skills——而 `git status` 在这个状态下**可以是干净的**（原因见下），所以"没报错"不等于好了。

## 先自检：你现在在哪种状态

```powershell
# 唯一可靠的判据：True = 目录/symlink（正常）；False = 需要修
(Get-Item .dsh\skills -Force).PSIsContainer

# 仅供参考（见下方"为什么不能只看 git status"）
git status --short -- .dsh/skills
```

| 状态 | `PSIsContainer` | 现象 |
|---|---|---|
| ① 真 symlink 或 junction（正常） | `True` | agent 能发现 skills |
| ② 普通文本文件（clone 默认） | `False` | 长度 9、内容 `../skills`；`git status` **可能为空** |
| ③ 破损的 reparse 点 | `False` | 长度 0、内容读不出；`git status` 显示 ` M .dsh/skills` |

**为什么不能只看 `git status`**：它取决于 `core.symlinks` 的**当前值**，同一个磁盘状态会给出不同答案。

- `core.symlinks=false`（Git for Windows 默认）：git 把"内容正好是 symlink 目标的普通文件"视为未变更 → 状态 ② 的 `git status --short -- .dsh/skills` 输出**为空**。
- `core.symlinks=true` 而磁盘上仍是那个文本文件：同一台机器上同一状态显示 ` T .dsh/skills`（类型变更）。

（两条都实测于 git 2.55.0.windows.5：先以默认 `false` 观察为空，随后 `git config core.symlinks true` 后同一文件变成 ` T`。）

所以"status 干净"既可能是修好了、也可能是状态 ②；只有"显示 ` T`"能确定没修好。**判据一律用 `PSIsContainer`**，别用 status。

## 修法（优先第一条）

**① 开真 symlink（首选）**：Windows 10+ 打开「开发者模式」即可免管理员建 symlink。clone 前 `git config --global core.symlinks true`；已经 clone 的原地修（不用重新 clone）：

```powershell
git config core.symlinks true
Remove-Item .dsh\skills -Force     # 删掉 clone 残留的文本文件（或破损的 reparse 点）
git checkout -- .dsh/skills        # 重新检出为真 symlink
```

修完 `git status` 干净，pull / rebase / reset 无任何特例。

**② 开不了开发者模式：用脚本建 junction**。`python3 scripts/enable_agent_skills.py`（Windows 上先试真 symlink，无权限自动退到 `mklink /J` 目录链接，免管理员），它还会自动对 `.dsh/skills` 打 `git update-index --skip-worktree`——消除「永久脏状态」与 `git pull --rebase` 每次都失败（该路径在仓库里是内容固定的 symlink 条目，日常 pull 不会碰它；万一上游真改了这个链接，git 会拒绝合并，按提示先 `git update-index --no-skip-worktree .dsh/skills` 再重来）。等价的手工版：

```powershell
# 在仓库根目录运行
foreach ($d in '.dsh','.claude','.cursor','.trae','.codebuddy','.codex') {
  New-Item -ItemType Directory -Force $d | Out-Null
  # 清掉克隆残留的同名文本文件（若非目录）
  if ((Test-Path "$d\skills") -and -not (Get-Item "$d\skills" -Force).PSIsContainer) { Remove-Item "$d\skills" -Force }
  if (-not (Test-Path "$d\skills")) { New-Item -ItemType Junction "$d\skills" -Target (Resolve-Path .\skills) | Out-Null }
}
git update-index --skip-worktree .dsh/skills   # 让 git 忽略 junction 造成的类型变更
```

> 别用 Git Bash 的 `ln -s` 补建：它在 Windows 上默认退化成**复制**，建出的是 `skills/` 目录副本，之后 git pull 更新 SKILL.md 不再同步（静默的知识库过期）。

## 与换行符无关，但同在 Windows 上会咬人

仓库已带 `.gitattributes`（`* text=auto eol=lf`），所有文本文件在 Windows 上也按 LF 检出，避免 CRLF 在 YAML/脚本里引发解析失败或 diff 噪音。

## 多 worktree 下的注意

`git worktree add` 新建的 worktree 同样按 `core.symlinks` 的当前值检出——上面三种状态在每个 worktree 里各自独立出现，**不要用主检出修好就假定 worktree 也好了**；每个检出各跑一次自检。
