"""evolve —— 自演进评估循环的核心包（v1）。

模块边界（依赖方向自下而上，核心不 import 适配器、CLI 或旧脚本）：

    contracts / object_types / metrics / statistics / decision / pools / policy
        纯数据、纯函数与策略校验；不读文件、不打印、不读环境变量。
    samples / records
        显式 IO 层：样本 YAML 与只追加 JSONL 记录；路径由调用方注入。
    ports
        Protocol 接口；不含实现。
    adapters
        旧脚本（s2_replay / verify_evidence / ev_proposal / 体检器）的薄包装；
        允许反向 import 旧脚本，核心模块不 import 这里。
    cli
        编排与命令行；scripts/evolve.py 是薄包装。

v1 只实现诊断对象的二元配对判定、样本队列与结论记录。trace 收集器、
A3 auto-merge、GEPA/SkillOpt 等扩展不在这里。
"""

__version__ = "0.1.0"
