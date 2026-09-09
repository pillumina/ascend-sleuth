#!/usr/bin/env python3
"""面板色语一致性检查 —— 同一界面里的面板必须用同一套颜色角色。

问题背景：两个面板各自定义语义色，同名角色用了不同色值（诊断面板 #22c55e 表示
"已解决"、演进面板 #15803d 表示"已采纳"），拼在一起就是两种风格。

契约（角色 → 用途 → 允许的取值来源）：
  --c-*    文字色  需过 WCAG AA，故用深一档同色相
  --acc-*  装饰色  点/条/边框/渐变（大块面，非文字）
  --fill-* 实心徽标底（白字或深字需过 AA）
  --btn-*  渐变按钮端色
本脚本校验两个面板声明的角色集合一致、且亮/暗两套都齐。

用法：python3 scripts/check_panel_tokens.py [--check]
返回非零 = 不一致。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PANELS = {
    'ev-panel': ROOT / 'dsh-plugins/ev-panel/panel-client.js',
    'ascend-panel': ROOT / 'dsh-plugins/ascend-panel/panel-client.js',
}
ROLES = ['--c-blue', '--c-green', '--c-purple', '--c-amber', '--c-red', '--c-gray',
         '--acc-blue', '--acc-green', '--acc-purple', '--acc-amber', '--acc-red', '--acc-gray']


def declared(text):
    """抓 '--role:#hex' 形式的声明，按亮/暗分别统计。

    以 'body[data-ds-dark-theme]' 出现位置切分亮色块与暗色块。
    """
    dark_at = text.find('body[data-ds-dark-theme]')
    light_part = text[:dark_at] if dark_at > 0 else text
    dark_part = text[dark_at:] if dark_at > 0 else ''
    def grab(part):
        out = {}
        for m in re.finditer(r'(--[a-z-]+):\s*(#[0-9a-fA-F]{6})', part):
            out.setdefault(m.group(1), m.group(2))
        return out
    return grab(light_part), grab(dark_part)


def main():
    problems = []
    report = {}
    for name, path in PANELS.items():
        text = path.read_text(encoding='utf-8')
        light, dark = declared(text)
        report[name] = (light, dark)
        missing_l = [r for r in ROLES if r not in light]
        missing_d = [r for r in ROLES if r not in dark]
        if missing_l:
            problems.append(f'{name}: 亮色缺角色 {missing_l}')
        if missing_d:
            problems.append(f'{name}: 暗色缺角色 {missing_d}')

    # 角色集合一致性
    sets = {n: (set(l) & set(ROLES), set(d) & set(ROLES)) for n, (l, d) in report.items()}
    names = list(sets)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            if sets[a][0] != sets[b][0]:
                problems.append(f'{a} 与 {b} 亮色角色集不一致：{sets[a][0] ^ sets[b][0]}')
            if sets[a][1] != sets[b][1]:
                problems.append(f'{a} 与 {b} 暗色角色集不一致：{sets[a][1] ^ sets[b][1]}')

    print('面板色语一致性：')
    for name, (l, d) in report.items():
        print(f'  {name}: 亮色 {len(set(l) & set(ROLES))}/{len(ROLES)} 角色 · 暗色 {len(set(d) & set(ROLES))}/{len(ROLES)} 角色')
    # 展示同角色是否同色（不一致不报错——文字色可各自调，但装饰色应一致）
    for role in ['--acc-blue', '--acc-green', '--acc-purple']:
        vals = {n: report[n][0].get(role) for n in report}
        uniq = set(v for v in vals.values() if v)
        mark = '一致' if len(uniq) <= 1 else '不一致: ' + str(vals)
        print(f'  {role}: {mark}')

    if problems:
        print('\n失败：')
        for p in problems:
            print('  - ' + p)
        return 1
    print('\nOK：两面板角色集合一致')
    return 0


if __name__ == '__main__':
    sys.exit(main())
