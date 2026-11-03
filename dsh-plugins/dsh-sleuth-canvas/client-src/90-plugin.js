// 插件装配：styles 注入、host RPC 适配、两个注册面（主区整页 + 左栏图标）。
//
// 常驻插件包的 client 半没有动态沙箱的 `host` / `styles` 全局，这里按同样的语义补：
//   SC.host.call(endpoint, payload)  → connection.rpc.call('/sleuth-canvas', endpoint, payload)
//   apply 里插入 <style>，卸载时移除。

  const CHANNEL = '/sleuth-canvas'
  const PANEL_ID = 'sleuth-canvas'
  const PANEL_LABEL = '诊断画布'

  function makeHost(ctx) {
    const connection = ctx.get('connection')
    return {
      call(endpoint, payload) {
        if (!connection || !connection.rpc || typeof connection.rpc.call !== 'function') {
          return Promise.reject(new Error('connection 服务不可用：拿不到 DSH 的 RPC 通道'))
        }
        return connection.rpc
          .call(CHANNEL, String(endpoint), payload === undefined ? {} : payload)
          .then(function (outer) {
            if (!outer || outer.ok !== true) {
              const failure = outer && outer.error
              throw new Error(failure && failure.message ? failure.message : 'RPC 失败')
            }
            return outer.value
          })
      },
    }
  }

  // 与 package 的 icon.svg 同形的侧栏图标：圆角方框里一条旅程曲线 + 三个节点。
  function CanvasIcon(props) {
    const size = props && typeof props.size === 'number' ? props.size : 18
    return SC.h(
      'svg',
      {
        viewBox: '0 0 24 24',
        width: size,
        height: size,
        fill: 'none',
        stroke: 'currentColor',
        strokeWidth: 1.55,
        strokeLinecap: 'round',
        strokeLinejoin: 'round',
        'aria-hidden': 'true',
      },
      SC.h('rect', { x: 3.4, y: 3.4, width: 17.2, height: 17.2, rx: 5 }),
      SC.h('path', { d: 'M6.4 16.2c3.2 0 3.2-6.4 6.4-6.4s3.2 4.6 6.4 4.6' }),
      SC.h('circle', { cx: 6.4, cy: 16.2, r: 1.25, fill: 'currentColor', stroke: 'none' }),
      SC.h('circle', { cx: 12.8, cy: 9.8, r: 1.25, fill: 'currentColor', stroke: 'none' }),
      SC.h('circle', { cx: 19.2, cy: 14.4, r: 1.25, fill: 'currentColor', stroke: 'none' }),
    )
  }

  SC.CanvasIcon = CanvasIcon

  SC.plugin = {
    name: 'dsh-sleuth-canvas',
    inject: ['slots', 'connection'],
    apply(ctx) {
      const slots = ctx.get('slots')
      if (slots === undefined) {
        console.error('[sleuth-canvas] slots 服务不可用，界面不注册')
        return
      }
      SC.host = makeHost(ctx)

      const disposers = []
      try {
        const styleTag = document.createElement('style')
        styleTag.dataset.sleuthCanvas = 'true'
        styleTag.textContent = String(SC.css || '')
        document.head.appendChild(styleTag)
        disposers.push(function () { styleTag.remove() })
      } catch (error) {
        console.error('[sleuth-canvas] 样式注入失败: ' + String((error && error.message) || error))
      }

      try {
        disposers.push(slots.inject('main', function () {
          return slots.register({ name: 'main', key: PANEL_ID }, SC.CanvasPage)
        }))
        disposers.push(slots.inject('sidebar.panellist', function () {
          return slots.register({
            name: 'sidebar.panellist',
            id: PANEL_ID,
            order: 40,
            label: PANEL_LABEL,
          }, CanvasIcon)
        }))
      } catch (error) {
        console.error('[sleuth-canvas] 注册失败: ' + String((error && error.message) || error))
      }

      return function dispose() {
        for (const dispose of disposers) {
          try {
            if (typeof dispose === 'function') dispose()
          } catch (error) { /* 一个卸不掉不阻塞其余 */ }
        }
      }
    },
  }
