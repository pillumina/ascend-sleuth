#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_bmc_report.py — 一键：解析 iBMC 一键收集日志 → JSON → 精美 HTML 报告。

用法：
  python run_bmc_report.py <日志根目录1> [根目录2 ...] -o <输出目录>
  # 日志根目录也可以直接给 .zip / .tar.gz / .tgz / .tar 收集包，自动解压后解析
  # 输出:
  #   <输出目录>/<机器名>_bmc.json        (每台机器独立 JSON，单/多机都有)
  #   <输出目录>/all_machines_bmc.json    (多机时: machines + comparison 矩阵)
  #   <输出目录>/BMC诊断报告_<机型>_<SN>.html        (单机报告)
  #   <输出目录>/BMC诊断报告_集群对比_N机器.html     (多机集群对比，多机时)
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PARSE = os.path.join(HERE, "parse_bmc_collect.py")
GEN = os.path.join(HERE, "generate_bmc_report.py")


def py(cmd):
    return subprocess.run([sys.executable] + cmd, check=True)


def machine_name(d, jsons=None, j=None):
    ident = d.get("identity", {})
    name = ident.get("product_name") or d.get("versions", {}).get("product_name") or "unknown"
    sn = ident.get("product_sn") or d.get("machine_tag") or "unknown"
    base = re.sub(r'[\\/:*?"<>|]', "_", f"{name}_{sn}")
    # 若多机 SN 冲突（同机型同 SN 的不同目录），追加来源 JSON 文件名后缀区分。
    # 注意 JSON 文件名为 "<机型>_<SN>_bmc.json"，须用子串匹配而非 startswith(SN)。
    if jsons is not None and j is not None and len(jsons) > 1:
        sn_key = ident.get("product_sn", "")
        if sn_key and sum(1 for x in jsons if sn_key in os.path.basename(x)) > 1:
            base += "_" + os.path.splitext(os.path.basename(j))[0][-20:]
    return base


def extract_archive(root, out_dir):
    """压缩包自动解压：zip / tar.gz / tgz / tar → <输出目录>/_extracted/<包名>/。

    是压缩包则返回解压目录，否则返回 None（调用方按普通日志目录传入）。
    """
    low = root.lower()
    base = os.path.basename(root)
    try:
        if low.endswith(".zip"):
            import zipfile
            dest = os.path.join(out_dir, "_extracted", os.path.splitext(base)[0])
            os.makedirs(dest, exist_ok=True)
            with zipfile.ZipFile(root) as zf:
                zf.extractall(dest)
            return dest
        if low.endswith((".tar.gz", ".tgz", ".tar")):
            import tarfile
            dest = os.path.join(out_dir, "_extracted",
                                re.sub(r"\.(tar\.gz|tgz|tar)$", "", base, flags=re.IGNORECASE))
            os.makedirs(dest, exist_ok=True)
            with tarfile.open(root) as tf:
                try:  # filter 参数仅 Python 3.12+/较新 3.11 支持，老版本回退
                    tf.extractall(dest, filter="data")
                except TypeError:
                    tf.extractall(dest)
            return dest
    except Exception as e:
        print(f"警告: 解压失败 {root}: {e}，将按普通目录尝试解析。")
        return None
    return None


def main():
    # Windows 控制台默认 cp936，打印中文路径/提示时可能 UnicodeEncodeError
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("roots", nargs="+",
                    help="一个或多个日志根目录（也支持 .zip/.tar.gz/.tgz/.tar 压缩包，自动解压）")
    ap.add_argument("-o", "--output-dir", required=True)
    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    # 清理上次运行遗留的中间 JSON，避免历史机器混入本次报告（HTML 报告不受影响）
    for old in glob.glob(os.path.join(args.output_dir, "*_bmc.json")):
        try:
            os.remove(old)
        except OSError:
            pass

    # 压缩包 → 解压目录；普通目录原样传入
    roots = []
    for r in args.roots:
        ex = extract_archive(r, args.output_dir)
        if ex:
            print(f"已解压: {r} -> {ex}")
            roots.append(ex)
        else:
            roots.append(r)

    py([PARSE] + roots + ["-o", args.output_dir])

    # 收集 per-machine JSON（排除 all_machines）
    jsons = sorted(glob.glob(os.path.join(args.output_dir, "*_bmc.json")))
    jsons = [j for j in jsons if "all_machines" not in j]
    machines = []
    for j in jsons:
        with open(j, "r", encoding="utf-8") as f:
            machines.append(json.load(f))
    if not machines:
        print("未生成任何机器 JSON：请确认传入的是 iBMC 一键收集日志根目录"
              "（内含 dump_info/ 等子目录），且压缩包能正常解压。")
        sys.exit(1)

    if len(roots) > len(jsons):
        print(f"警告: 传入 {len(roots)} 个日志根目录，但只产出 {len(jsons)} 份机器 JSON，"
              "可能存在机型与 SN 完全相同的多台机器相互覆盖，请核对各机 SN。")

    if len(machines) == 1:
        out = os.path.join(args.output_dir,
                           f"BMC诊断报告_{machine_name(machines[0], jsons, jsons[0])}.html")
        py([GEN, jsons[0], "-o", out])
        print("single report:", out)
    else:
        # 多机：只出一个集群对比报告（内嵌各机详情）
        out_multi = os.path.join(args.output_dir,
                                 f"BMC诊断报告_集群对比_{len(machines)}台机器.html")
        py([GEN, *jsons, "-o", out_multi])
        print("cluster report:", out_multi)

    print("done.")


if __name__ == "__main__":
    main()
