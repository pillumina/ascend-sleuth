    const React = require('react')
    const h = React.createElement

    const CHANNEL = '/sleuth-copilot'
    const NS = 'sleuth-copilot'
    // 与 package.json 的 version 一起改；页面上的版本串是判断装没装到新版的依据。
    const PLUGIN_VERSION = '0.25.1'
    const POLL_MS = 10000
    // 查合入的逐条进度：主 RPC 在跑时每 500 ms 问一次进度端点；连续 3 次失败就静默停轮询，
    // 不打断整批（最终结果仍以主 RPC 为准）。
    const PR_PROGRESS_POLL_MS = 500
    const PR_PROGRESS_MAX_FAILURES = 3
    // 去同步后点开「知识库」标签：整页是异步挂载的，查早了没有标签，短轮询等它出现。
    const KB_TAB_OPEN_POLL_MS = 100
    const KB_TAB_OPEN_WAIT_MS = 1500
    // 同步要跑一会儿：点「去同步」后隔 30 秒复查一次，还落后再隔 60 秒复查（共约 90 秒）。
    // 每次带 force 让 host 跳过 60 秒节流；行还在才挂下一次。
    const KB_RECHECK_DELAYS_MS = [30000, 60000]
    const PREFS_KEY = 'dsh-sleuth-copilot.prefs.v2'
    const FILTER_KEYS = ['all', 'open', 'pending', 'sediment']
    // PR 记录允许的状态（与 scripts/pr_status.py 的 STATES 一致）。
    const PR_STATE_KEYS = ['open', 'merged', 'closed', 'unknown']
    // 详情抬头默认收起成四行；「展开全文」优先看实际溢出（scrollHeight > clientHeight）。
    // 离线渲染没有布局引擎，拿不到尺寸时退回这个字数近似：四行在 400–510px 列宽下约 110–150 字，
    // 取小值，宁可多给一个入口也不把内容藏起来。
    const LEDE_TOGGLE_MIN = 110
    // 选中行取时间线四层的去抖：方向键连按时只发最后一次，不堆子进程。
    const LAYERS_DEBOUNCE_MS = 130

