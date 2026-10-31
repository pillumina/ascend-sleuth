#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vendor 子技能桥接器：调用 vendor/ 下的 cluster-output-analysis 与 prof-compare。

子命令：
  cluster  生成 cluster-output-analysis 子报告
           cluster_data_extractor.py 提取 JSON -> generate_cluster_report.py 渲染
           输出: <reports-dir>/cluster_analysis_report.html

  compare  生成 prof-compare 子报告
           在 --compare-dir 中查找 performance_comparison_result_*.xlsx，
           交给 vendor main_analyzer.py 分析
           输出: <reports-dir>/compare_analysis_report.html
                 <reports-dir>/compare_analysis_result.json
                 <reports-dir>/chinese_xlsx/

所有子报告统一落在 <mw>/reports/ 下，供总报告（performance_report.html）
通过相对路径 reports/*.html 以 iframe 内嵌加载。
"""
import argparse
import glob
import json
import os
import subprocess
import sys

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR_CLUSTER = os.path.join(SKILL_DIR, 'vendor', 'cluster-output-analysis', 'scripts')
VENDOR_CLUSTER_TPL = os.path.join(SKILL_DIR, 'vendor', 'cluster-output-analysis', 'templates')
VENDOR_COMPARE = os.path.join(SKILL_DIR, 'vendor', 'prof-compare', 'scripts')


def run(cmd, cwd=None):
    """运行子进程，返回 (returncode, stdout+stderr)。"""
    print('[vendor_bridge] ' + ' '.join(cmd))
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           encoding='utf-8', errors='ignore')
        out = (p.stdout or '') + (p.stderr or '')
        if out.strip():
            for line in out.strip().splitlines()[-30:]:
                print('  | ' + line)
        return p.returncode, out
    except Exception as e:  # noqa: BLE001
        print(f'  ! 执行失败: {e}')
        return 1, str(e)


def cmd_cluster(args):
    data_dir = os.path.abspath(args.data_dir)
    reports_dir = os.path.abspath(args.reports_dir)
    os.makedirs(reports_dir, exist_ok=True)

    # vendor 提取器内部按 <data-dir>/cluster_analysis_output/cluster_analysis.db 寻找，
    # 因此传入 cluster_analysis_output 的父目录
    if os.path.basename(data_dir) == 'cluster_analysis_output':
        extract_dir = os.path.dirname(data_dir)
    else:
        extract_dir = data_dir

    if not (os.path.isfile(os.path.join(extract_dir, 'cluster_analysis_output', 'cluster_analysis.db'))
            or os.path.isfile(os.path.join(extract_dir, 'cluster_analysis_output', 'cluster.db'))
            or os.path.isfile(os.path.join(extract_dir, 'cluster.db'))
            or os.path.isfile(os.path.join(extract_dir, 'cluster_analysis_output', 'cluster_step_trace_time.csv'))
            or os.path.isfile(os.path.join(extract_dir, 'cluster_step_trace_time.csv'))):
        print('SKIP: 未找到 cluster 数据（cluster_analysis.db / cluster_step_trace_time.csv）')
        return 2

    extract_json = os.path.join(reports_dir, 'cluster_data.json')
    rc, _ = run([sys.executable, os.path.join(VENDOR_CLUSTER, 'cluster_data_extractor.py'),
                 '--data-dir', extract_dir, '--output', extract_json])
    if rc != 0 or not os.path.isfile(extract_json):
        print('ERROR: cluster_data_extractor 执行失败')
        return 1

    out_html = os.path.join(reports_dir, 'cluster_analysis_report.html')
    rc, _ = run([sys.executable, os.path.join(VENDOR_CLUSTER, 'generate_cluster_report.py'),
                 '--mode', 'single', '--data', extract_json,
                 '--template-dir', VENDOR_CLUSTER_TPL, '--output', out_html])
    if rc != 0 or not os.path.isfile(out_html):
        print('ERROR: generate_cluster_report 执行失败')
        return 1
    print(f'OK: {out_html}')
    return 0


def cmd_compare(args):
    compare_dir = os.path.abspath(args.compare_dir)
    reports_dir = os.path.abspath(args.reports_dir)
    os.makedirs(reports_dir, exist_ok=True)

    xlsx_list = sorted(glob.glob(os.path.join(compare_dir, 'performance_comparison_result_*.xlsx')))
    if not xlsx_list:
        print('SKIP: 未找到 performance_comparison_result_*.xlsx（可能 pandas/openpyxl 不可用）')
        return 2

    rc, _ = run([sys.executable, os.path.join(VENDOR_COMPARE, 'main_analyzer.py'),
                 xlsx_list[0], '-o', reports_dir],
                cwd=VENDOR_COMPARE)
    out_html = os.path.join(reports_dir, 'compare_analysis_report.html')
    if rc != 0 or not os.path.isfile(out_html):
        print('ERROR: prof-compare main_analyzer 执行失败')
        return 1
    print(f'OK: {out_html}')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='cmd', required=True)

    p1 = sub.add_parser('cluster', help='生成 cluster-output-analysis 子报告')
    p1.add_argument('--data-dir', required=True,
                    help='cluster_analysis_output 目录（或其父目录）')
    p1.add_argument('--reports-dir', required=True,
                    help='子报告输出目录（<mw>/reports）')
    p1.set_defaults(func=cmd_cluster)

    p2 = sub.add_parser('compare', help='生成 prof-compare 子报告')
    p2.add_argument('--compare-dir', required=True,
                    help='包含 performance_comparison_result_*.xlsx 的目录（<mw>/compare）')
    p2.add_argument('--reports-dir', required=True,
                    help='子报告输出目录（<mw>/reports）')
    p2.set_defaults(func=cmd_compare)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == '__main__':
    main()
