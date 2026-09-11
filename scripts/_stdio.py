#!/usr/bin/env python3
# _stdio.py —— 把 stdin/stdout/stderr 钉成 UTF-8（Windows 兼容）
#
# 为什么需要：Windows 上三个标准流接到**管道/文件**时用 locale 编码（中文系统 =
# cp936/GBK），只有接到真控制台才走 UTF-16 通道。后果三类：
#   ① 输出里的非 GBK 字符（−、✓、⚠、✅、↔、⏭ 等）→ UnicodeEncodeError，
#      进程非零退出且 stdout 为空（面板拿到空串，只能显示 traceback）；
#   ② 中文本身能编码，但产出 GBK 字节，被按 UTF-8 解码的采集方读成乱码
#      （DSH 的 shell 采集器按 UTF-8 解码子进程输出）；
#   ③ 输入侧镜像问题：管道喂进来的 UTF-8 字节按 cp936 解码 → UnicodeDecodeError
#      （如 `gh pr view --json body --jq .body | python3 scripts/verify_pr_body.py`）。
# 三者同源：仓库的数据契约是 UTF-8（文件、YAML/JSON、PR body 全是 UTF-8），
# 但"进程标准流的编码"没跟着钉住。放在这里，各脚本入口调一次即可。
#
# 用法（脚本 __main__ 块首行）：
#     from _stdio import pin_utf8_stdio
#     pin_utf8_stdio()

import sys


def write_text_lf(path, text, encoding: str = "utf-8") -> None:
    """写文本文件并**固定 LF 换行**（Windows 兼容）。

    为什么需要（都不是"只是噪声"）：
      ① 入库产物在 Windows 上被 `Path.write_text()` 写成 CRLF，`git status` 出现
         内容为空的 phantom 修改，reviewer 与 `git add -A` 都被干扰；
      ② 更硬的一类：`build_index.case_hash()` 与 `holdout` 的封存哈希都是
         `read_bytes()` 的 SHA-256——**按字节**算。用 CRLF 写出的 case / fixture，
         在 Windows 上重建索引并提交后，Linux CI 检出的是 LF，哈希对不上 →
         `--check` 必然判 STALE（红），而失败信息只说"过期"，看不出是行尾所致。
    Linux 上本就是 LF，改用本函数无行为差异。
    """
    with open(path, "w", encoding=encoding, newline="\n") as fh:
        fh.write(str(text))


def pin_utf8_stdio() -> None:
    """把 sys.stdin / sys.stdout / sys.stderr 重配为 UTF-8。

    已是 UTF-8、或流不支持 reconfigure（被替换成非文本流 / 已关闭）时静默跳过——
    这种情况下调用方本就没走 TextIOWrapper 的编码路径。
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", "") or "").replace("-", "").lower()
        if encoding == "utf8":
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except Exception:
            # 流已关闭 / 非 TextIOWrapper：保持原样，由调用方自行处理
            pass
