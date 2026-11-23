"""evolve —— 自演进评估循环的核心包（v1）。

模块边界（依赖方向自下而上，核心不 import 适配器、CLI 或旧脚本）：

    contracts / object_types / metrics / statistics / decision / pools / policy
        纯数据、纯函数与策略校验；不读文件、不打印、不读环境变量。
    samples / records
        显式 IO 层：样本 YAML 与只追加 JSONL 记录；路径由调用方注入。
    store
        RSI 事件存储：models 定义事件、ports 定义 Backend 端口、local / memory
        是两个实现，service 只依赖端口。
    errors
        领域错误基类；各模块的错误仍按 ValueError / RuntimeError 区分方向。
    targets / algorithms / sources / stages
        各扩展面的静态注册表；一个目标的全部事实在 targets.registry.TARGETS。
    evaluations
        评测面注册表（哪个 target 走哪套 scorer/gate）与门禁执行（gates.py 读文件、
        起子进程）。
    usage / usage_dimensions
        用量维度的共用骨架与接线表；CLI 子命令、pilot 约束、flow 证据都从表里取。
    adapters
        旧脚本（s2_replay / fetch_issues / issue_filter / 体检器）的薄包装；
        允许反向 import 旧脚本，核心模块不 import 这里。
    cli
        编排与命令行；scripts/evolve.py 是薄包装。

v1 只实现诊断对象的二元配对判定、样本队列与结论记录。trace 收集器、
A3 auto-merge、GEPA/SkillOpt 等扩展不在这里。

包外依赖只有 ``scripts/`` 下三个共享原语（``_fs`` / ``exec_log_path`` /
``sleuth_config``），以 ``scripts/`` 在 sys.path 为前提；入口 ``scripts/evolve.py``
已保证这一点，新增这类依赖要在 ``tests/self_evolution/test_architecture.py`` 的
``ALLOWED_SCRIPT_PRIMITIVES`` 登记，否则架构测试报红。
"""

__version__ = "0.1.0"
