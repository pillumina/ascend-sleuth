# -*- coding: utf-8 -*-
"""共享常量：目录名、产物名、通信算子正则。

单一事实来源（SSOT）：所有跨脚本共享的常量只允许定义在这里
（约定见 references/pipeline.md「扩展守则」）。
"""

import re

# 中间件根目录名（run_workflow 创建）
MW_NAME = 'cluster_analysis_mw'

# 中间件内的固定目录 / 产物名
DETECT_JSON = 'detect_result.json'
DIR_ADVISOR = 'advisor'
DIR_CLUSTER_OUTPUT = 'cluster_analysis_output'
DIR_COMPARE = 'compare'
DIR_REPORTS = 'reports'
DIR_SWIMLANE = 'swimlane'
REPORT_HTML = 'performance_report.html'

# vendor_bridge 返回码约定：2 = 输入缺失/不支持，跳过不算失败
VENDOR_RC_SKIP = 2

# communication.json 中的聚合行名（原 advisor / compare / recipe 三处各自定义）
AGG_ROWS = {'Total Op Info', 'Total Info', 'total'}

# 通信算子名称判定（统一并集：hcom_* / hccl* / sync_data / notify_* / allreduceAicpu / nccl*）
# 原 advisor_fallback / compare_fallback / recipe_fallback / swimlane_analyzer 四处各自定义且互不一致，
# 收敛于此；修改前需确认对全部调用方成立。
COMM_NAME_PATTERN = re.compile(r'(hcom_|hccl|sync_data|notify_|allreduceAicpu|nccl)', re.IGNORECASE)


def is_comm_op(name):
    """判定算子名是否为通信算子。"""
    return bool(COMM_NAME_PATTERN.search(name or ''))
