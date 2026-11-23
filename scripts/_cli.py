#!/usr/bin/env python3
"""命令行公共层：UTF-8 标准流、退出码、JSON 输出。

为什么单独一个模块：多个脚本各自 ``sys.exit(main())``，其中一部分入口忘了把 stdio
钉成 UTF-8——Windows 上输出接管道时，``→`` / ``✗`` 这类字符会抛 UnicodeEncodeError，
进程非零退出且 stdout 为空。入口统一走 :func:`main_entry` 后，"钉 stdio、BrokenPipe 与
KeyboardInterrupt 的收尾"只在一处。

退出码只定义三个通用含义；脚本特有的码仍由脚本自己返回：
    0  成功 / 没有要报的问题
    1  有发现（校验不过、判定不符预测）
    2  用法或读取错误（参数不合法、文件读不到）
"""

from __future__ import annotations

import json
import sys

from _stdio import pin_utf8_stdio

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


def emit(payload) -> None:
    """一行 UTF-8 JSON（不改字段、不转义中文）。"""
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def fail(message: str, code: int = EXIT_USAGE) -> int:
    """把错误写到 stderr 并返回退出码（调用方 ``return fail(...)``）。"""
    print(message, file=sys.stderr, flush=True)
    return code


def main_entry(main) -> int:
    """入口包装：钉 stdio，把 SystemExit / BrokenPipe / Ctrl-C 归一成整数退出码。

    其他异常照常抛出——吞掉 traceback 会让真正的 bug 看起来像一次普通失败。
    """
    pin_utf8_stdio()
    try:
        result = main()
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return EXIT_OK
        if isinstance(code, int):
            return code
        print(code, file=sys.stderr, flush=True)
        return EXIT_FINDINGS
    except BrokenPipeError:
        return EXIT_OK
    except KeyboardInterrupt:
        return 130
    return int(result or EXIT_OK)
