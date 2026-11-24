    // ── 注册 ────────────────────────────────────────────────────────────────
    function registerLocale(ctx) {
      const locale = ctx.get('locale')
      if (locale === undefined || typeof locale.register !== 'function') return () => {}
      const disposers = []
      for (const [lang, dict] of Object.entries(DICTS)) {
        try {
          const dispose = locale.register(NS, lang, dict)
          if (typeof dispose === 'function') disposers.push(dispose)
        } catch {
          // 语言 id 不被这个版本接受时保留内置中文表
        }
      }
      try {
        const bound = locale.bind(NS)
        if (typeof bound === 'function') {
          translate = (key, params) => {
            let text
            try {
              text = bound(key)
            } catch {
              text = ''
            }
            return formatText(text || ZH[key] || key, params)
          }
        }
      } catch {
        // bind 失败就用内置中文表
      }
      return () => {
        for (const dispose of disposers) {
          try {
            dispose()
          } catch {
            // 卸载阶段清理失败不影响后续
          }
        }
      }
    }

    function insertStyles() {
      const tag = document.createElement('style')
      tag.setAttribute('data-dsh-sleuth-copilot', '1')
      tag.textContent = CSS
      document.head.appendChild(tag)
      return () => {
        try {
          tag.remove()
        } catch {
          // 页面卸载时 head 可能已被清空
        }
      }
    }

    function makeRpc(ctx) {
      const connection = ctx.get('connection')
      return async function rpc(endpoint, payload) {
        if (connection === undefined || connection.rpc === undefined || typeof connection.rpc.call !== 'function') {
          throw new Error('connection 服务不可用')
        }
        const outer = await connection.rpc.call(CHANNEL, String(endpoint), payload === undefined ? {} : payload)
        if (outer === undefined || outer.ok !== true) {
          const failure = outer && outer.error
          throw new Error(failure && failure.message ? failure.message : 'RPC 失败')
        }
        return outer.value
      }
    }

    function makeOpenSession(ctx) {
      return async function openSession(id) {
        const target = String(id || '')
        if (!target) return { ok: false, reason: '没有会话号' }
        const candidates = []
        try {
          const sessions = ctx.get('sessions')
          if (sessions) candidates.push(sessions)
        } catch {
          // 没有这个服务就只试下一个
        }
        try {
          const uiWorkspace = ctx.get('uiWorkspace')
          if (uiWorkspace) candidates.push(uiWorkspace)
        } catch {
          // 同上
        }
        for (const host of candidates) {
          for (const name of ['openSession', 'open', 'select', 'selectSession', 'show', 'activate']) {
            let fn
            try {
              fn = host[name]
            } catch {
              continue
            }
            if (typeof fn !== 'function') continue
            try {
              fn.call(host, target)
              return { ok: true }
            } catch (error) {
              const why = String((error && error.message) || error)
              if (!/unknown session|not listed|不存在/i.test(why)) continue
              try {
                if (candidates[0] && typeof candidates[0].refresh === 'function') await candidates[0].refresh()
              } catch {
                // 刷新失败就按原样报
              }
              try {
                fn.call(host, target)
                return { ok: true }
              } catch (second) {
                return { ok: false, reason: '拉过最新列表仍然没有这一条：' + String((second && second.message) || second) }
              }
            }
          }
        }
        return { ok: false, reason: '没有可用的打开会话接口' }
      }
    }

    function withInputActions(Component) {
      return function SurfaceWithInputs(props) {
        const inputActions = props && props.inputActions
        React.useEffect(() => {
          if (!inputActions) return undefined
          surfaceInputs.push(inputActions)
          return () => {
            const index = surfaceInputs.indexOf(inputActions)
            if (index >= 0) surfaceInputs.splice(index, 1)
          }
        }, [inputActions])
        return h(Component, props)
      }
    }

    return {
      // 显式声明用到的服务：cordis 只对声明过的服务名建键，未声明的 ctx.get 返回 undefined。
      // 「切到该诊断的会话」必须有 sessions；uiWorkspace 只是后备，继续用 ctx.get 探测——
      // 声明一个旧发行版没有的服务会让整条状态条一直等它，代价高于收益。
      // layout（去同步切整页）同理不声明，走 probeLayout 的探针 + 动态注册。
      inject: ['connection', 'slots', 'sessions'],
      apply(ctx) {
        const slots = ctx.get('slots')
        if (slots === undefined) return
        rpcCall = makeRpc(ctx)
        openSessionImpl = makeOpenSession(ctx)
        probeLayout(ctx)
        selectPanelImpl = makeSelectPanel()
        ctx.effect(() => registerLocale(ctx), 'sleuth-copilot: locale')
        ctx.effect(() => stopTimer, 'sleuth-copilot: poll timer')
        ctx.effect(() => insertStyles(), 'sleuth-copilot: styles')
        // 知识库提示的复查与标签轮询挂在插件生命周期：状态条会随整页切换被卸载，不能绑在组件上。
        ctx.effect(() => () => clearKbTimers(), 'sleuth-copilot: kb timers')

        const Dock = withInputActions(makeDock())
        const Toolbar = withInputActions(ToolbarButton)

        ctx.effect(() => slots.inject('conversation.input.dock', () => slots.register({
          name: 'conversation.input.dock',
          id: 'sleuth-copilot',
          order: 55,
        }, Dock)), 'sleuth-copilot: input dock')

        ctx.effect(() => slots.inject('conversation.input.right', () => slots.register({
          name: 'conversation.input.right',
          id: 'sleuth-copilot-toolbar',
          order: 5,
        }, Toolbar)), 'sleuth-copilot: input toolbar')

        ctx.effect(() => slots.inject('shell.overlay', () => slots.register({
          name: 'shell.overlay',
          id: 'sleuth-copilot-palette',
          order: 60,
        }, Palette)), 'sleuth-copilot: palette')
      },
    }
