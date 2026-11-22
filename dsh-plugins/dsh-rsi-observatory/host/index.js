// dsh-rsi-observatory —— host 半：RSI 实验台的只读数据服务
//
// 职责只有三件：
//   1. 解析会话工作区（含 scripts/rsi_observatory.py 的那份检出）与 Python 解释器；
//   2. 经 shell 跑只读桥脚本，拿到归一化 JSON；
//   3. 注册 /rsi-observatory 的 prefix RPC 路由，把两份数据（list / detail）发给前端。
//
// 数据只经 RSIStore 的 open_store/read/history 取（在 scripts/rsi_observatory.py 里），本文件
// 不读 JSONL、不解析事件、不写仓库。shell 服务缺席时如实返回 E_NO_SHELL，不拿别处的数据冒充。
//
// 路由信封与 dsh-sleuth-canvas 对齐：
//   POST <channel>/<endpoint>，body {type:'client-request', rpcId, method, payload}
//   应答 {type:'server-response', rpcId, result}，result 为 {ok,value} 或 {ok:false,error}
// 不用 connection.rpc.handle（owner 绑在 connection 服务自己的 ctx，注册时读不到 webServer）。

const CHANNEL = '/rsi-observatory'
const MAX_BODY_BYTES = 1024 * 1024
const SCRIPT_REL = 'scripts/rsi_observatory.py'
const DEFAULT_CACHE_TTL_MS = 30000
const ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/
const PYTHON_RE = /^[A-Za-z0-9._/\\-]+(?: -3)?$/
const PYTHON_CANDIDATES = ['python3', 'python', 'py -3']

function codedError(code, message, details) {
  const error = new Error(message)
  error.code = code
  error.details = details === undefined ? {} : details
  return error
}

function stdoutText(result) {
  return result && result.stdout && typeof result.stdout.text === 'string' ? result.stdout.text : ''
}

function stderrText(result) {
  return result && result.stderr && typeof result.stderr.text === 'string' ? result.stderr.text : ''
}

// 两种 shell 形状都要吃：动态沙箱的 run(spec)，或常驻服务的 execute(spec) + result()。
async function runShell(shell, spec) {
  if (typeof shell.run === 'function') return await shell.run(spec)
  if (typeof shell.execute === 'function') {
    const execution = await shell.execute(spec)
    return typeof execution.result === 'function' ? await execution.result() : execution
  }
  throw codedError('E_NO_SHELL', 'shell 服务没有 run/execute，实验台取不到数据')
}

export function apply(ctx, config) {
  const options = config && typeof config === 'object' ? config : {}
  const configRepo = typeof options.repo === 'string' && options.repo.trim() ? options.repo.trim() : ''
  const configPython = typeof options.python === 'string' && options.python.trim() ? options.python.trim() : ''
  const cacheTtlMs = Number.isFinite(Number(options.cacheTtlMs)) && Number(options.cacheTtlMs) > 0
    ? Number(options.cacheTtlMs)
    : DEFAULT_CACHE_TTL_MS

  const handlers = new Map()
  const cache = new Map()
  let pythonCmd = ''

  function readPolicy(sessionId) {
    const service = ctx.get('sandboxPolicy')
    if (!service || typeof service.resolve !== 'function') return undefined
    const sessions = ctx.get('sessions')
    let session = null
    try {
      session = sessionId && sessions ? sessions.get(sessionId) : null
    } catch (error) {
      session = null
    }
    if (!session && sessions && typeof sessions.list === 'function') {
      try {
        for (const item of sessions.list() || []) {
          if (item && item.header && item.header.cwd) {
            session = item
            break
          }
        }
      } catch (error) {
        session = null
      }
    }
    try {
      const policy = session ? service.resolve({ session }) : service.resolve()
      return policy && typeof policy.mode === 'string' ? policy : undefined
    } catch (error) {
      return undefined
    }
  }

  function sessionCwds(sessionId) {
    const dirs = []
    if (configRepo) dirs.push(configRepo)
    const sessions = ctx.get('sessions')
    if (!sessions) return dirs.filter((dir, index) => dirs.indexOf(dir) === index)
    if (sessionId) {
      try {
        const session = sessions.get(sessionId)
        if (session && session.header && session.header.cwd) dirs.push(String(session.header.cwd))
      } catch (error) {
        // 会话不在列表里：继续用其余候选
      }
    }
    try {
      for (const session of sessions.list() || []) {
        const cwd = session && session.header && session.header.cwd
        if (cwd) dirs.push(String(cwd))
      }
    } catch (error) {
      // 拿不到会话列表：只剩 config.repo / 直接候选
    }
    return dirs.filter((dir, index) => dir && dirs.indexOf(dir) === index)
  }

  async function pickRepo(sessionId) {
    const dirs = sessionCwds(sessionId)
    if (!dirs.length) return null
    const fs = ctx.get('fs')
    if (!fs || typeof fs.resolve !== 'function' || typeof fs.stat !== 'function') {
      // 没有 fs 就不猜：把第一个候选交给 shell，脚本不存在时由它的报错暴露
      return dirs[0]
    }
    for (const dir of dirs) {
      try {
        const target = await fs.resolve(SCRIPT_REL, { cwd: dir })
        await fs.stat(target)
        return dir
      } catch (error) {
        // 这个候选不含桥脚本：试下一个
      }
    }
    return null
  }

  function shellResolve(command, cwd, policy) {
    const shell = ctx.get('shell')
    const spec = shell.resolve({
      command,
      workdir: cwd,
      stdoutMaxBytes: 4 * 1024 * 1024,
      env: { PYTHONIOENCODING: 'utf-8' },
      ...(policy ? { sandboxPolicy: policy } : {}),
    })
    return spec
  }

  async function resolvePython(shell, cwd, policy) {
    if (configPython) {
      if (!PYTHON_RE.test(configPython)) {
        throw codedError('E_NO_PYTHON', 'Config.python 含不支持的字符：' + configPython)
      }
      return configPython
    }
    if (pythonCmd) return pythonCmd
    const failures = []
    for (const candidate of PYTHON_CANDIDATES) {
      try {
        const result = await runShell(shell, shellResolve(candidate + ' --version', cwd, policy))
        const output = stdoutText(result) + '\n' + stderrText(result)
        if (result && result.exitCode === 0 && /Python 3\./.test(output)) {
          pythonCmd = candidate
          return candidate
        }
        failures.push(candidate + ' 不可用（退出码 ' + String(result && result.exitCode) + '）')
      } catch (error) {
        failures.push(candidate + ' 执行失败：' + String((error && error.message) || error))
      }
    }
    throw codedError(
      'E_NO_PYTHON',
      '未找到可用的 Python 3 解释器（已试 ' + PYTHON_CANDIDATES.join(' / ') + '）——'
        + '实验台的数据桥需要它；装好 Python 3 并放进 PATH，或在 Config.python 指定解释器。'
        + (failures.length ? '\n' + failures.join('\n') : ''),
    )
  }

  async function runBridge(sessionId, args) {
    const shell = ctx.get('shell')
    if (!shell || (typeof shell.run !== 'function' && typeof shell.execute !== 'function')) {
      throw codedError('E_NO_SHELL', '当前宿主不提供 shell 服务，实验台取不到数据。')
    }
    const cwd = await pickRepo(sessionId)
    if (!cwd) {
      throw codedError(
        'E_NO_REPO',
        '定位不到含 ' + SCRIPT_REL + ' 的检出：请在 Config.repo 填绝对路径，或从该检出开一个会话。',
      )
    }
    const policy = readPolicy(sessionId)
    const python = await resolvePython(shell, cwd, policy)
    const command = python + ' ' + SCRIPT_REL + ' ' + args.join(' ')
    let result
    try {
      result = await runShell(shell, shellResolve(command, cwd, policy))
    } catch (error) {
      if (error && error.code === 'E_NO_SHELL') throw error
      throw codedError(
        'E_BRIDGE',
        '实验台数据桥没跑起来：' + String((error && error.message) || error)
          + '\n手工复现：在仓库根目录执行 ' + command,
      )
    }
    const stdout = stdoutText(result)
    const stderr = stderrText(result)
    if (result && result.exitCode === 4) {
      throw codedError('E_NOT_FOUND', String(stderr || '找不到这条实验').slice(0, 800))
    }
    if (!stdout.trim()) {
      const message = String(stderr || '').slice(0, 800)
      if (/no module named ['"]?(yaml|pyyaml)/i.test(message)) {
        throw codedError(
          'E_PYTHON_DEPS',
          '运行实验台数据桥需要 PyYAML：' + python + ' -m pip install pyyaml 后重开面板。\n' + message,
          { command },
        )
      }
      throw codedError(
        'E_STORE',
        (message || '数据桥没有输出') + '\n脚本 ' + SCRIPT_REL + '（工作目录 ' + cwd + '）',
        { command },
      )
    }
    let data
    try {
      data = JSON.parse(stdout)
    } catch (error) {
      throw codedError('E_BRIDGE', SCRIPT_REL + ' 输出不是 JSON：' + String((error && error.message) || error))
    }
    return { data, cwd }
  }

  async function cached(key, refresh, run) {
    const now = Date.now()
    if (!refresh) {
      const hit = cache.get(key)
      if (hit && hit.expiresAt > now) {
        if (hit.error) throw hit.error
        return hit.value
      }
    }
    try {
      const value = await run()
      cache.set(key, { expiresAt: now + cacheTtlMs, value })
      return value
    } catch (error) {
      // 失败同样按窗口复用（避免每次挂载都重跑一遍），但 refresh:true 能强制重试。
      cache.set(key, { expiresAt: now + cacheTtlMs, error })
      throw error
    }
  }

  async function handleList(payload) {
    const sessionId = payload && typeof payload.sessionId === 'string' ? payload.sessionId : ''
    const refresh = Boolean(payload && payload.refresh)
    const result = await cached('list:' + sessionId, refresh,
      () => runBridge(sessionId, ['list', '--json']))
    return result.data
  }

  async function handleDetail(payload) {
    const sessionId = payload && typeof payload.sessionId === 'string' ? payload.sessionId : ''
    const refresh = Boolean(payload && payload.refresh)
    const key = payload && typeof payload.experimentId === 'string' ? payload.experimentId : ''
    if (!ID_RE.test(key)) {
      throw codedError('E_ARGS', 'experimentId 形状不对：只接受字母、数字与 . _ -，长度 1–64')
    }
    const result = await cached('detail:' + sessionId + ':' + key, refresh,
      () => runBridge(sessionId, ['detail', '--experiment', key, '--json']))
    return result.data
  }

  handlers.set('rsi-list', handleList)
  handlers.set('rsi-detail', handleDetail)

  function registerRoute(webCtx) {
    const dispose = webCtx.effect(() => webCtx.webServer.register({
      kind: 'prefix',
      path: CHANNEL,
      handler: async (req, res) => {
        if (req.method !== 'POST') {
          res.setHeader('Allow', 'POST')
          res.writeHead(405)
          res.end()
          return
        }
        const rejection = webCtx.get('connection')?.requestRejection?.(req)
        if (rejection !== undefined) {
          res.writeHead(rejection)
          res.end(rejection === 401 ? 'unauthorized' : 'forbidden')
          return
        }
        const chunks = []
        let received = 0
        for await (const chunk of req) {
          received += chunk.length
          if (received > MAX_BODY_BYTES) {
            res.writeHead(413)
            res.end('payload too large')
            return
          }
          chunks.push(chunk)
        }
        let body
        try {
          body = JSON.parse(Buffer.concat(chunks).toString('utf8'))
        } catch (error) {
          res.writeHead(400)
          res.end('body is not JSON')
          return
        }
        const rawPath = new URL(req.url === undefined ? '/' : req.url, 'http://localhost').pathname
        const pathEndpoint = rawPath.startsWith(CHANNEL + '/') ? rawPath.slice(CHANNEL.length + 1) : ''
        const endpoint = pathEndpoint !== ''
          ? pathEndpoint
          : (typeof body.method === 'string' ? body.method : '')
        const handler = handlers.get(endpoint)
        let result
        if (handler === undefined) {
          result = {
            ok: false,
            error: { code: 'not-found', message: '未知的 RPC 端点: ' + endpoint, details: {} },
          }
        } else {
          try {
            const payload = body === undefined || body.payload === undefined ? {} : body.payload
            result = { ok: true, value: await handler(payload) }
          } catch (error) {
            result = {
              ok: false,
              error: {
                code: String((error && error.code) || 'internal'),
                message: String((error && error.message) || error),
                details: (error && error.details) || {},
              },
            }
          }
        }
        res.writeHead(200, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify({
          type: 'server-response',
          rpcId: body === undefined ? undefined : body.rpcId,
          result,
        }))
      },
    }), 'dsh-rsi-observatory: ' + CHANNEL + ' rpc route')
    console.error('[dsh-rsi-observatory] RPC 路由已注册: ' + CHANNEL)
    return dispose
  }

  try {
    if (typeof ctx.inject !== 'function') {
      console.error('[dsh-rsi-observatory] ctx.inject 不可用，RPC 路由未注册')
    } else {
      ctx.inject(['webServer'], registerRoute)
    }
  } catch (error) {
    console.error('[dsh-rsi-observatory] webServer 服务不可用，RPC 路由未注册: '
      + String((error && error.message) || error))
  }

  return () => {
    handlers.clear()
    cache.clear()
  }
}

// 测试入口：纯函数从这里取，node 直跑 test/host.test.mjs。
export const __test = {
  CHANNEL,
  MAX_BODY_BYTES,
  SCRIPT_REL,
  ID_RE,
  runShell,
}
