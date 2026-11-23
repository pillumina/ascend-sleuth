    // ── 切到 Ascend Sleuth 整页（去同步用）──────────────────────────────────
    // layout 是侧栏 shell 的服务，但不写进 exports.inject：声明成必需服务会让整条状态条在
    // 缺它的宿主上进入 waiting，「去同步」这一个动作不该拖垮状态条。写法与 ascend-panel 取
    // sessions 一致：先探针，再用 ctx.inject 动态注册；都拿不到就保持 null，调用方降级成
    // 一句装面板的指引。
    let layoutService = null
    function noteLayout(value) {
      if (layoutService) return
      if (!value || typeof value !== 'object') return
      layoutService = value
    }
    function probeLayout(ctx) {
      layoutService = null
      try { noteLayout(ctx.get('layout')) } catch { /* 未声明时可能抛 */ }
      try {
        if (typeof ctx.inject === 'function') {
          ctx.inject(['layout'], (scope) => {
            try { noteLayout(scope.get('layout')) } catch { /* 子 fiber 也没有就保持 null */ }
          })
        }
      } catch { /* 注册失败就只靠前面的探针 */ }
    }
    let selectPanelImpl = () => false
    function makeSelectPanel() {
      return function selectPanel(id) {
        try {
          if (!layoutService || typeof layoutService.selectPanel !== 'function') return false
          layoutService.selectPanel(String(id))
          return true
        } catch {
          return false
        }
      }
    }

    const surfaceInputs = []
    function findInputActions() {
      for (const surface of surfaceInputs) {
        if (surface && typeof surface.setDraft === 'function') return surface
      }
      return null
    }

