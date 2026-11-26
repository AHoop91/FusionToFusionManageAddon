// Runs the DOM tests (tests/js/dom) in a real browser: Edge or Chrome, headless, driven over the DevTools protocol with Node's own WebSocket.
// Nothing is installed and no server is started: the files are sent into one page, which runs the tests (in-page.js) and sends the outcome back.
//
// Run: node tests/js/browser/run.mjs [test files...]     Exit: 0 passed, 1 failed, 77 no browser found (the Python suite skips on 77).
// Set MFG_TEST_BROWSER to the browser's path to choose one.
import { spawn, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, '..', '..', '..')
const TEST_TIMEOUT = 30000
const RUN_TIMEOUT = 300000
const SETUP_TIMEOUT = 30000   // the browser starts, shows the page: three waits of this size and RUN_TIMEOUT stay under the Python test's 600 s
const NO_BROWSER = 77
const TOTAL_TIMEOUT = 480000   // everything: below the 600 s the Python test gives it

const posix = (p) => p.split(path.sep).join('/')

function findBrowser() {
  const env = process.env
  if (env.MFG_TEST_BROWSER) {   // a browser that was asked for and is not there is an error, not a reason to skip
    if (!fs.existsSync(env.MFG_TEST_BROWSER)) throw new Error('MFG_TEST_BROWSER is set to ' + env.MFG_TEST_BROWSER + ', which does not exist.')
    return env.MFG_TEST_BROWSER
  }
  const candidates = []
  if (process.platform === 'win32') {
    for (const base of [env['ProgramFiles(x86)'], env.ProgramFiles, env.LOCALAPPDATA]) {
      if (!base) continue
      candidates.push(path.join(base, 'Microsoft', 'Edge', 'Application', 'msedge.exe'), path.join(base, 'Google', 'Chrome', 'Application', 'chrome.exe'))
    }
  } else if (process.platform === 'darwin') {
    candidates.push('/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
  } else {
    for (const name of ['microsoft-edge', 'google-chrome', 'chromium', 'chromium-browser']) {
      for (const dir of (env.PATH || '').split(path.delimiter)) candidates.push(path.join(dir, name))   // looked for on the PATH here: a minimal system may have no `which`
    }
  }
  return candidates.find((c) => c && fs.existsSync(c)) || null
}

/** Every file a test can read: the web page's html and scripts, the languages, and the tests themselves, by their path under the repository. */
function collect() {
  const files = {}
  const walk = (dir, keep) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) walk(full, keep)
      else if (keep(entry.name)) files[posix(path.relative(ROOT, full))] = fs.readFileSync(full, 'utf8')
    }
  }
  walk(path.join(ROOT, 'src', 'ui', 'web'), (name) => /\.(html|js)$/.test(name))
  walk(path.join(ROOT, 'tests', 'js'), (name) => /\.(js|mjs)$/.test(name))
  files['resources/languages/en.json'] = fs.readFileSync(path.join(ROOT, 'resources', 'languages', 'en.json'), 'utf8')
  return files
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

/** promise, or fallback() once ms have passed; the timer is cleared so that it does not keep Node waiting. */
async function within(promise, ms, fallback) {
  let timer
  try { return await Promise.race([promise, new Promise((resolve, reject) => { timer = setTimeout(() => { try { resolve(fallback()) } catch (error) { reject(error) } }, ms) })]) } finally { clearTimeout(timer) }
}

/** ``read()`` until it answers something; a ``read`` that throws (the browser is not listening yet) is tried again until ``ms`` are up, and the last error is said. */
async function until(what, read, ms) {
  const end = Date.now() + ms
  let last = null
  for (;;) {
    try {
      const value = await read()
      if (value) return value
    } catch (error) { if (error.fatal) throw error; last = error }
    if (Date.now() > end) throw new Error('timed out waiting for ' + what + (last ? ' (' + last.message + ')' : ''))
    await sleep(100)
  }
}

/** A DevTools connection to one page: ``send`` a command, get its result; ``on`` an event. A command still waiting when the socket closes is rejected. */
async function connect(url) {
  const socket = new WebSocket(url)
  await within(new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = () => reject(new Error('could not connect to the browser')) }), SETUP_TIMEOUT, () => { throw new Error('the browser did not answer the connection') })
  let id = 0
  const waiting = new Map()
  const handlers = new Map()
  socket.onclose = () => { waiting.forEach((w) => w.reject(new Error('the browser closed the connection'))); waiting.clear() }
  socket.onmessage = (message) => {
    const data = JSON.parse(message.data)
    if (data.id !== undefined) {
      const w = waiting.get(data.id)
      waiting.delete(data.id)
      if (data.error) w.reject(new Error(data.error.message)); else w.resolve(data.result)
    } else if (handlers.has(data.method)) handlers.get(data.method)(data.params)
  }
  return {
    send: (method, params) => new Promise((resolve, reject) => {
      if (socket.readyState !== WebSocket.OPEN) { reject(new Error('the browser closed the connection')); return }
      id += 1
      waiting.set(id, { resolve, reject })
      socket.send(JSON.stringify({ id, method, params: params || {} }))
    }),
    on: (method, handler) => handlers.set(method, handler),
    close: () => socket.close(),
  }
}

/** A real origin for the page, with nothing behind it: the browser asks for http://localhost/ and is answered here, so storage works as it does in the add-in.
 *  Gives up after ``SETUP_TIMEOUT``; a request that could not be answered fails the setup. */
async function openBlankPage(page) {
  let refused
  const failed = new Promise((resolve, reject) => { refused = reject })
  page.on('Fetch.requestPaused', (e) => {
    const root = new URL(e.request.url).pathname === '/'
    page.send('Fetch.fulfillRequest', {
      requestId: e.requestId, responseCode: root ? 200 : 404,
      responseHeaders: [{ name: 'Content-Type', value: 'text/html' }],
      body: Buffer.from(root ? '<!doctype html><html><body></body></html>' : '').toString('base64'),
    }).catch(refused)
  })
  const setup = (async () => {
    await page.send('Fetch.enable', { patterns: [{ urlPattern: 'http://localhost/*' }] })
    await page.send('Page.enable')
    const loaded = new Promise((resolve) => page.on('Page.loadEventFired', resolve))
    await page.send('Page.navigate', { url: 'http://localhost/' })
    await loaded
  })()
  await within(Promise.race([setup, failed]), SETUP_TIMEOUT, () => { throw new Error('the browser did not open the page within ' + SETUP_TIMEOUT / 1000 + ' s') })
}

/** Resolves when the browser's own process has ended. */
const ended = (child) => new Promise((resolve) => { if (!child || child.exitCode !== null) resolve(); else child.on('exit', resolve) })

/** Stop the browser and everything it started, and remove its profile. A profile that cannot be removed is said, not thrown: it must not replace the report. */
function stop(child, profile) {
  if (child && child.pid) {
    if (process.platform === 'win32') spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'])   // always: the launcher can be gone while its renderers hold the profile
    else { try { process.kill(-child.pid, 'SIGKILL') } catch (error) { child.kill('SIGKILL') } }
  }
  if (!profile) return
  try { fs.rmSync(profile, { recursive: true, force: true, maxRetries: 50, retryDelay: 200 }) } catch (error) { console.warn('Could not remove ' + profile + ': ' + error.message) }
}

function report(outcome) {
  const marks = { pass: '✔', fail: '✖', skip: '−' }
  let failed = 0
  let passed = 0
  let skipped = 0
  let file = null
  for (const r of outcome.results) {
    if (r.file !== file) { file = r.file; console.log('\n' + file) }
    console.log(`  ${marks[r.status]} ${r.name} (${r.ms}ms)`)
    if (r.status === 'fail') { failed += 1; console.log(r.error.split('\n').map((l) => '      ' + l).join('\n')) } else if (r.status === 'skip') skipped += 1; else passed += 1
  }
  for (const e of outcome.loadErrors) { failed += 1; console.log(`\n${e.file} did not load\n` + e.error.split('\n').map((l) => '      ' + l).join('\n')) }
  console.log(`\ntests ${outcome.results.length}\npass ${passed}\nfail ${failed}\nskipped ${skipped}`)
  if (passed + failed === 0) { console.log('no test ran: that is a failure'); return 1 }
  return failed ? 1 : 0
}

async function main() {
  const browser = findBrowser()   // throws for a MFG_TEST_BROWSER that is not there
  if (!browser) { console.error('No Edge or Chrome found (set MFG_TEST_BROWSER to one).'); return NO_BROWSER }
  const given = process.argv.slice(2).map((p) => posix(path.relative(ROOT, path.resolve(p))))
  const files = collect()
  const entries = given.length ? given : Object.keys(files).filter((k) => /^tests\/js\/dom\/(.+\/)?[^/]+\.test\.js$/.test(k)).sort()
  let profile = null
  let child = null
  let page = null
  try {
    profile = fs.mkdtempSync(path.join(os.tmpdir(), 'mfg-browser-'))   // a profile of its own, or the browser hands over to one the user has open and exits
    let started = null   // what went wrong with the browser's own start: it could not run, or it ended
    child = spawn(browser, [
      '--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`, '--no-first-run', '--no-default-browser-check', '--disable-extensions',
      '--disable-gpu', '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--window-size=1280,900', 'about:blank',
    ], { stdio: 'ignore', detached: process.platform !== 'win32' })
    const watchdog = setTimeout(() => { console.error('the run took more than ' + TOTAL_TIMEOUT / 1000 + ' s: the browser is stopped'); stop(child, profile); process.exit(1) }, TOTAL_TIMEOUT)   // the Python test must never be the one to time out: it would leave the browser
    watchdog.unref()
    child.on('error', (error) => { started = error })
    child.on('exit', (code) => { started = started || new Error('the browser ended with code ' + code + ' before it was ready') })
    const fatal = () => { if (started) { started.fatal = true; throw started } }
    const port = await until('the browser to start', () => {
      fatal()
      try { return fs.readFileSync(path.join(profile, 'DevToolsActivePort'), 'utf8').split('\n')[0] } catch (error) { return null }
    }, SETUP_TIMEOUT)
    const target = await until('the page', async () => {
      fatal()
      const list = await (await fetch(`http://127.0.0.1:${port}/json/list`, { signal: AbortSignal.timeout(5000) })).json()
      return list.find((t) => t.type === 'page')
    }, SETUP_TIMEOUT)
    page = await connect(target.webSocketDebuggerUrl)
    await openBlankPage(page)
    const inPage = fs.readFileSync(path.join(HERE, 'in-page.js'), 'utf8')
    const run = page.send('Runtime.evaluate', {
      expression: `(${inPage})(${JSON.stringify({ files, entries, timeout: TEST_TIMEOUT })})`, awaitPromise: true, returnByValue: true,
    })
    const result = await within(run, RUN_TIMEOUT, () => { throw new Error('the run took more than ' + RUN_TIMEOUT / 1000 + ' s') })
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception ? result.exceptionDetails.exception.description : result.exceptionDetails.text)
    return report(result.result.value)
  } finally {
    if (page) {   // asked to close first: its helper processes then end by themselves and let go of the profile; stopped below if it does not
      try { await within(page.send('Browser.close'), 3000, () => null) } catch (error) { /* the browser ended, or it is stopped below */ }
      page.close()
    }
    await within(ended(child), 3000, () => null)
    stop(child, profile)
  }
}

main().then((code) => { process.exitCode = code }, (error) => { console.error(error); process.exitCode = 1 })
