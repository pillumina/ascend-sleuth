"""Native offline disclosure for complete evidence tables."""
import re
from html import escape
from pathlib import Path

DISPLAY_LIMIT = 100


def limit_table(markup):
    """Truncate rendered rows only; original analysis/JSON is untouched."""
    rows = list(re.finditer(r'<tr\b[^>]*>.*?</tr>', markup, re.S))
    data_rows = [row for row in rows if '<td' in row.group(0)]
    prior = re.search(r'data-total-rows="(\d+)"', markup)
    total = int(prior.group(1)) if prior else len(data_rows)
    if len(data_rows) > DISPLAY_LIMIT:
        for match in reversed(data_rows[DISPLAY_LIMIT:]):
            markup = markup[:match.start()] + markup[match.end():]
    if total > DISPLAY_LIMIT and not prior:
        markup = re.sub(r'<table\b', '<table data-total-rows="%d"' % total, markup, count=1)
        markup = re.sub(r'(<table\b[^>]*>)', r'\1<caption>仅展示前 100 / %d 条；完整记录见 report_data.json</caption>' % total, markup, count=1)
    return markup


def limit_markdown_tables(text):
    lines = text.splitlines()
    result, i = [], 0
    while i < len(lines):
        if lines[i].startswith('|') and i + 1 < len(lines) and re.match(r'^\|[- :|]+\|$', lines[i + 1]):
            result.extend(lines[i:i + 2]); i += 2
            rows = []
            while i < len(lines) and lines[i].startswith('|'):
                rows.append(lines[i]); i += 1
            result.extend(rows[:DISPLAY_LIMIT])
            if len(rows) > DISPLAY_LIMIT:
                result.extend(['', '仅展示前 100 / %d 条；完整记录见 report_data.json。' % len(rows), ''])
        else:
            result.append(lines[i]); i += 1
    return '\n'.join(result)


def disclose_table(markup, title='完整明细', count=None, force=False):
    if count is None:
        prior = re.search(r'data-total-rows="(\d+)"', markup)
        count = int(prior.group(1)) if prior else max(0, len(re.findall(r'<tr\b', markup)) - 1)
    markup = limit_table(markup)
    if 'data-inline-help' in markup or (not force and count <= 12):
        return markup
    return ('<details class="data-details"><summary>%s（共 %d 条记录，最多展示100条）</summary>'
            '<div class="table-tools"><label>搜索 <input data-table-search type="search" placeholder="关键词 / CPU / TID"></label>'
            '<label>排序列 <select data-table-sort></select></label>'
            '<button type="button" data-table-direction>升序</button>'
            '<span data-table-count>显示 %d / %d 条</span></div>%s</details>') % (escape(title), count, min(count, DISPLAY_LIMIT), count, markup)


def enhance_long_tables(html):
    """Cover legacy hand-written tables too; never duplicate an existing wrapper."""
    html = re.sub(r'<table\b[^>]*>.*?</table>', lambda match: limit_table(match.group(0)), html, flags=re.S)
    pattern = re.compile(r'<details\b[^>]*class="data-details"[^>]*>.*?</details>|<table\b[^>]*>.*?</table>', re.S)
    return pattern.sub(lambda match: match.group(0) if match.group(0).startswith('<details') else disclose_table(match.group(0)), html)


def table_script():
    return '<script>' + (Path(__file__).parent / 'assets/report_tables.js').read_text(encoding='utf-8-sig') + '</script>'
