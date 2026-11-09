"""口径脚本的单元测试（EV-2026-108）。

护的是什么：`scripts/` 里的 `--check` 卡口验的是"仓库自洽"（索引新鲜、schema 合法、
id 唯一、生成物一致），不验"算得对"。而 `build_index` / `trace_metrics` /
`settle_trace_feedback` / `build_timeline` 四个脚本的口径一旦写错，CI 全绿、面板与
置信度静默报错数，下游的门控判决跟着错。这里给这四个脚本的口径与边界加最小回归保护。

约定：不联网、不读真实 `traces/`（那是含客户信息的运行时件，CI 里也不存在），
一律用 tmp 目录构造输入；断言打在**口径值**上，不打在私有实现细节上。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from _stdio import pin_utf8_stdio  # noqa: E402

# 显式按模块名跑（CI 分片、本地单跑某个 test_x）不会导入其它测试模块。Windows 上进程
# stdout 接管道时默认用 locale 编码（cp1252/cp936），任何在进程内 print 非 ASCII 的测试
# 都会 UnicodeEncodeError。全量 discover 一直是绿的，是因为它导入全部模块，其中某个模块
# 在 import 时调了 pin_utf8_stdio()——分片暴露了这份对导入顺序的隐式依赖。在包入口钉一次，
# 选中哪几个模块都一样。
pin_utf8_stdio()
