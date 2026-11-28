#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_bmc_report.py — 一键：解析 iBMC 一键收集日志 → JSON → 精美 HTML 报告。

用法：
  python run_bmc_report.py <日志根目录1> [根目录2 ...] -o <输出目录>
  # 日志根目录也可以直接给 .zip / .tar.gz / .tgz / .tar 收集包，自动解压后解析
  # 输出:
  #   <输出目录>/<机器名>[_<SN>]_bmc.json   (每台机器独立 JSON，单/多机都有)
  #   <输出目录>/all_machines_bmc.json    (多机时: machines + comparison 矩阵)
  #   <输出目录>/BMC诊断报告_<机型>_<SN>.html        (单机报告)
  #   <输出目录>/BMC诊断报告_集群对比_N机器.html     (多机集群对比，多机时)
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

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


def _archive_parts(name):
    """把压缩包成员名拆成安全的分段；绝对路径、盘符与 .. 一律拒绝。"""
    normalized = str(name).replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise ValueError(f"压缩包路径越界：{name}")
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise ValueError(f"压缩包路径越界：{name}")
    return parts


def _safe_target(root, name):
    parts = _archive_parts(name)
    target = os.path.realpath(os.path.join(root, *parts))
    try:
        inside = os.path.commonpath([root, target]) == root
    except ValueError:
        inside = False
    if not inside:
        raise ValueError(f"压缩包路径越界：{name}")
    return target


def _safe_extract_zip(zf, dest):
    """拒绝越界路径与符号链接，避免一键收集包写出输出目录。"""
    root = os.path.realpath(dest)
    entries = []
    for member in zf.infolist():
        target = _safe_target(root, member.filename)
        if (member.external_attr >> 16) & 0o170000 == 0o120000:
            raise ValueError(f"拒绝符号链接：{member.filename}")
        entries.append((member, target))
    for member, target in entries:
        if member.is_dir():
            os.makedirs(target, exist_ok=True)
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with zf.open(member) as source, open(target, "wb") as output:
            shutil.copyfileobj(source, output)


def _safe_extract_tar(tf, dest):
    """逐成员校验路径与类型后解包；不依赖不同 Python 版本才有的 filter 参数。

    tarfile.extractall 的 filter="data" 只在较新解释器可用，旧版本回退到无校验的
    extractall 会让 ../../ 条目或链接写出目标目录。这里先校验全部成员、再统一解包：
    绝对路径、盘符、.. 逸出、符号链接/硬链接和设备文件一律拒绝，且不会在拒绝前
    把前面几个良性成员写进目标目录。
    """
    root = os.path.realpath(dest)
    entries = []
    for member in tf.getmembers():
        target = _safe_target(root, member.name)
        if member.issym() or member.islnk():
            raise ValueError(f"拒绝链接：{member.name}")
        if not (member.isdir() or member.isfile()):
            raise ValueError(f"拒绝特殊文件：{member.name}")
        entries.append((member, target))
    for member, target in entries:
        if member.isdir():
            os.makedirs(target, exist_ok=True)
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        source = tf.extractfile(member)
        if source is None:
            raise ValueError(f"无法读取成员：{member.name}")
        with source, open(target, "wb") as output:
            shutil.copyfileobj(source, output)


def extract_archive(root, out_dir):
    """压缩包自动解压：zip / tar.gz / tgz / tar → <输出目录>/_extracted/<包名>-<随机>/<包名>/。

    每个压缩包每次都用独立父目录，避免复用输出目录时上次解包的同名文件混进本次解析；
    内层用稳定的包名，机器标签不会带随机后缀。是压缩包则返回解压目录，否则返回 None
    （调用方按普通日志目录传入）。
    """
    low = root.lower()
    base = os.path.basename(root)
    stem = re.sub(r"\.(tar\.gz|tgz|tar|zip)$", "", base, flags=re.IGNORECASE) or "archive"
    stem = re.sub(r"[^\w.-]+", "_", stem)
    run_dir = None
    dest = None
    try:
        if low.endswith((".zip", ".tar.gz", ".tgz", ".tar")):
            os.makedirs(os.path.join(out_dir, "_extracted"), exist_ok=True)
            run_dir = tempfile.mkdtemp(
                prefix=f"{stem}-", dir=os.path.join(out_dir, "_extracted")
            )
            dest = os.path.join(run_dir, stem)
            os.makedirs(dest, exist_ok=True)
        if low.endswith(".zip"):
            import zipfile
            with zipfile.ZipFile(root) as zf:
                _safe_extract_zip(zf, dest)
            return dest
        if low.endswith((".tar.gz", ".tgz", ".tar")):
            import tarfile
            with tarfile.open(root) as tf:
                _safe_extract_tar(tf, dest)
            return dest
    except Exception as e:
        if run_dir:
            shutil.rmtree(run_dir, ignore_errors=True)
        print(f"警告: 解压失败 {root}: {e}，未继续解析。")
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
    # 解包目录也是中间产物：本次每个包会新建独立目录，旧目录不再复用
    for old in glob.glob(os.path.join(args.output_dir, "_extracted", "*")):
        shutil.rmtree(old, ignore_errors=True)

    # 压缩包 → 解压目录；普通目录原样传入
    roots = []
    archive_suffixes = (".zip", ".tar.gz", ".tgz", ".tar")
    for r in args.roots:
        ex = extract_archive(r, args.output_dir)
        if ex:
            print(f"已解压: {r} -> {ex}")
            roots.append(ex)
        elif r.lower().endswith(archive_suffixes):
            print(f"错误: 压缩包解压失败或包含不安全路径，未继续解析: {r}", file=sys.stderr)
            sys.exit(2)
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
              "可能有输入未被解析，请核对每个输入是否包含有效的 dump_info/。")

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
