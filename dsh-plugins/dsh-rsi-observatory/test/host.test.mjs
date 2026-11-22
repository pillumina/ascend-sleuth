// host 半测试：路由注册、两条 RPC 的信封、参数校验、错误码与结果复用窗口。
// 不依赖 DSH、不跑真 Python：shell 用 stub，数据用 fixtures。

import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { apply, __test } from '../host/index.js'

const listFixture = JSON.parse(readFileSync(new URL('./fixtures/list.json', import.meta.url), 'utf8'))
const detailFixture = JSON.parse(readFileSync(new URL('./fixtures/detail.json', import.meta.url), 'utf8'))

function ok(text) {
  return { exitCode: 0, stdout: { text }, stderr: { text: '' } }
}

function fail(code, text) {
  return { exitCode: code, stdout: { text: '' }, stderr: { text } }
}

function makeShell(handler) {
  const calls = []
  const shell = {
    calls,
    resolve(spec) { return spec },
    async run(spec) {
      calls.push(spec)
      if (handler) {
        const result = handler(spec)
        if (result !== undefined) return result
      }
      const command = String(spec.command)
      if (command.includes('--version')) return ok('Python 3.12.0\n')
      if (command.includes(' list ')) return ok(JSON.stringify(listFixture))
      if (command.includes(' detail ')) return ok(JSON.stringify(detailFixture))
      return fail(3, 'unexpected command: ' + command)
    },
  }
  return shell
}

function makeCtx(services) {
  const registered = []
  const webCtx = {
    get(name) { return services[name] },
    effect(fn) {
      const dispose = fn()
      return () => { if (typeof dispose === 'function') dispose() }
    },
    webServer: {
      register(options) {
        registered.push(options)
        return () => {}
      },
    },
  }
  const ctx = {
    get(name) { return services[name] },
    inject(names, callback) { callback(webCtx) },
  }
  return { ctx, webCtx, registered }
}

function makeSessions(cwd = '/repo') {
  return {
    get() { return { header: { cwd } } },
    list() { return [{ header: { cwd } }] },
  }
}

function makeRes() {
  return {
    status: 0,
    headers: {},
    body: '',
    setHeader(key, value) { this.headers[key] = value },
    writeHead(status) { this.status = status },
    end(text) { this.body = text === undefined ? '' : String(text) },
  }
}

async function post(route, endpoint, payload, options = {}) {
  const method = options.method || 'POST'
  const req = {
    method,
    url: '/rsi-observatory/' + endpoint,
    async *[Symbol.asyncIterator]() {
      yield Buffer.from(JSON.stringify({
        type: 'client-request',
        rpcId: options.rpcId || 'r1',
        method: endpoint,
        payload: payload === undefined ? {} : payload,
      }))
    },
  }
  const res = makeRes()
  await route.handler(req, res)
  return { status: res.status, body: res.body ? JSON.parse(res.body) : null }
}

test('注册一条 prefix 路由并返回卸载函数', () => {
  const shell = makeShell()
  const { ctx, registered } = makeCtx({ shell, sessions: makeSessions() })
  const dispose = apply(ctx, {})
  assert.equal(registered.length, 1)
  assert.equal(registered[0].kind, 'prefix')
  assert.equal(registered[0].path, __test.CHANNEL)
  assert.equal(typeof dispose, 'function')
  dispose()
  assert.equal(__test.SCRIPT_REL, 'scripts/rsi_observatory.py')
})

test('rsi-list 返回 server-response 信封与 fixture 数据', async () => {
  const shell = makeShell()
  const { ctx, registered } = makeCtx({ shell, sessions: makeSessions() })
  apply(ctx, {})
  const { status, body } = await post(registered[0], 'rsi-list', { sessionId: 's1' })
  assert.equal(status, 200)
  assert.equal(body.type, 'server-response')
  assert.equal(body.rpcId, 'r1')
  assert.equal(body.result.ok, true)
  assert.equal(body.result.value.counts.experiments, listFixture.counts.experiments)
  const listCall = shell.calls.find((call) => String(call.command).includes(' list '))
  assert.ok(listCall, '应调用桥脚本的 list')
  assert.ok(listCall.command.endsWith('scripts/rsi_observatory.py list --json'))
  assert.equal(listCall.workdir, '/repo')
})

test('rsi-detail 把 experimentId 作为固定参数传给桥脚本', async () => {
  const shell = makeShell()
  const { ctx, registered } = makeCtx({ shell, sessions: makeSessions() })
  apply(ctx, {})
  const { body } = await post(registered[0], 'rsi-detail', { experimentId: 'E-abc123' })
  assert.equal(body.result.ok, true)
  const detailCall = shell.calls.find((call) => String(call.command).includes(' detail '))
  assert.ok(detailCall)
  assert.ok(detailCall.command.includes('detail --experiment E-abc123 --json'))
})

test('experimentId 形状不对时在起子进程之前拒绝', async () => {
  const shell = makeShell()
  const { ctx, registered } = makeCtx({ shell, sessions: makeSessions() })
  apply(ctx, {})
  const { body } = await post(registered[0], 'rsi-detail', { experimentId: 'E-1; rm -rf /' })
  assert.equal(body.result.ok, false)
  assert.equal(body.result.error.code, 'E_ARGS')
  assert.equal(shell.calls.length, 0)
})

test('没有 shell 服务时返回 E_NO_SHELL', async () => {
  const { ctx, registered } = makeCtx({ sessions: makeSessions() })
  apply(ctx, {})
  const { body } = await post(registered[0], 'rsi-list', {})
  assert.equal(body.result.ok, false)
  assert.equal(body.result.error.code, 'E_NO_SHELL')
})

test('定位不到检出时返回 E_NO_REPO', async () => {
  const shell = makeShell()
  const { ctx, registered } = makeCtx({ shell })
  apply(ctx, {})
  const { body } = await post(registered[0], 'rsi-list', {})
  assert.equal(body.result.ok, false)
  assert.equal(body.result.error.code, 'E_NO_REPO')
  assert.equal(shell.calls.length, 0)
})

test('store 读失败映射到 E_STORE 并保留 stderr 原文', async () => {
  const shell = makeShell((spec) => {
    if (String(spec.command).includes(' list ')) {
      return fail(3, 'error: RecordError: invalid JSON in /repo/.s2-replay/evolve/rsi-events.jsonl line 2')
    }
    return undefined
  })
  const { ctx, registered } = makeCtx({ shell, sessions: makeSessions() })
  apply(ctx, {})
  const { body } = await post(registered[0], 'rsi-list', {})
  assert.equal(body.result.ok, false)
  assert.equal(body.result.error.code, 'E_STORE')
  assert.match(body.result.error.message, /invalid JSON/)
})

test('缺 PyYAML 映射到 E_PYTHON_DEPS', async () => {
  const shell = makeShell((spec) => {
    if (String(spec.command).includes(' list ')) {
      return fail(1, "ModuleNotFoundError: No module named 'yaml'")
    }
    return undefined
  })
  const { ctx, registered } = makeCtx({ shell, sessions: makeSessions() })
  apply(ctx, {})
  const { body } = await post(registered[0], 'rsi-list', {})
  assert.equal(body.result.ok, false)
  assert.equal(body.result.error.code, 'E_PYTHON_DEPS')
})

test('结果按窗口复用，refresh 绕过窗口', async () => {
  const shell = makeShell()
  const { ctx, registered } = makeCtx({ shell, sessions: makeSessions() })
  apply(ctx, {})
  await post(registered[0], 'rsi-list', {})
  await post(registered[0], 'rsi-list', {})
  const countList = () => shell.calls.filter((call) => String(call.command).includes(' list ')).length
  assert.equal(countList(), 1)
  await post(registered[0], 'rsi-list', { refresh: true })
  assert.equal(countList(), 2)
})

test('失败结果同样按窗口复用，但可被 refresh 强制重试', async () => {
  let attempt = 0
  const shell = makeShell((spec) => {
    if (String(spec.command).includes(' list ')) {
      attempt += 1
      return attempt === 1 ? fail(3, 'boom') : ok(JSON.stringify(listFixture))
    }
    return undefined
  })
  const { ctx, registered } = makeCtx({ shell, sessions: makeSessions() })
  apply(ctx, {})
  const first = await post(registered[0], 'rsi-list', {})
  assert.equal(first.body.result.error.code, 'E_STORE')
  const second = await post(registered[0], 'rsi-list', {})
  assert.equal(second.body.result.error.code, 'E_STORE')
  const third = await post(registered[0], 'rsi-list', { refresh: true })
  assert.equal(third.body.result.ok, true)
})

test('非 POST 返回 405，未知端点返回 not-found', async () => {
  const shell = makeShell()
  const { ctx, registered } = makeCtx({ shell, sessions: makeSessions() })
  apply(ctx, {})
  const wrongMethod = await post(registered[0], 'rsi-list', {}, { method: 'GET' })
  assert.equal(wrongMethod.status, 405)
  const unknown = await post(registered[0], 'rsi-nope', {})
  assert.equal(unknown.body.result.ok, false)
  assert.equal(unknown.body.result.error.code, 'not-found')
})

test('只有 execute 形状的 shell 也能跑通（execute + result）', async () => {
  const calls = []
  const handler = (spec) => {
    const command = String(spec.command)
    if (command.includes('--version')) return ok('Python 3.12.0\n')
    if (command.includes(' list ')) return ok(JSON.stringify(listFixture))
    return fail(3, 'unexpected')
  }
  const shell = {
    calls,
    resolve(spec) { return spec },
    async execute(spec) {
      calls.push(spec)
      return { async result() { return handler(spec) } }
    },
  }
  const { ctx, registered } = makeCtx({ shell, sessions: makeSessions() })
  apply(ctx, {})
  const { body } = await post(registered[0], 'rsi-list', {})
  assert.equal(body.result.ok, true)
  const listCall = calls.find((call) => String(call.command).includes(' list '))
  assert.ok(listCall)
})
