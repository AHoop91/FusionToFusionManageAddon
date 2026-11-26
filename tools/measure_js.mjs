import fs from 'node:fs'
import path from 'node:path'
/**
 * Measure JavaScript functions against the guardrails in dev/architecture.md.
 *
 * Run: node tools/measure_js.mjs [--json] [paths...]   (run `npm install` once, for acorn)
 *
 * Reports every function over 80 lines, cyclomatic complexity over 10, nesting deeper than 3 or more than 4 parameters.
 * The module wrapper (the function that wraps a whole file) is skipped: it is the file, not a function.
 * Exits 1 if any function breaks a guardrail. Same limits as tools/measure_code.py.
 */
import * as acorn from 'acorn'
import { fileURLToPath } from 'node:url'

const MAX_LINES = 80, MAX_COMPLEXITY = 10, MAX_NESTING = 3, MAX_PARAMS = 4
const FN = new Set(['FunctionDeclaration', 'FunctionExpression', 'ArrowFunctionExpression'])
const BRANCH = new Set(['IfStatement', 'ForStatement', 'ForInStatement', 'ForOfStatement', 'WhileStatement',
  'DoWhileStatement', 'CatchClause', 'ConditionalExpression'])
const NEST = new Set(['IfStatement', 'ForStatement', 'ForInStatement', 'ForOfStatement', 'WhileStatement',
  'DoWhileStatement', 'TryStatement', 'SwitchStatement'])

function children(node) {
  const out = []
  for (const key of Object.keys(node)) {
    const v = node[key]
    if (Array.isArray(v)) v.forEach(c => c && typeof c.type === 'string' && out.push(c))
    else if (v && typeof v.type === 'string') out.push(v)
  }
  return out
}

function complexity(fn) {
  let score = 1
  const walk = n => {
    if (n !== fn && FN.has(n.type)) return
    if (BRANCH.has(n.type)) score++
    else if (n.type === 'SwitchCase' && n.test) score++
    else if (n.type === 'LogicalExpression') score++
    children(n).forEach(walk)
  }
  walk(fn)
  return score
}

function nesting(node, depth) {
  let deepest = depth
  for (const c of children(node)) {
    if (FN.has(c.type)) continue
    deepest = Math.max(deepest, nesting(c, depth + (NEST.has(c.type) ? 1 : 0)))
  }
  return deepest
}

function nameOf(fn, parent) {
  if (fn.id) return fn.id.name
  if (parent && parent.type === 'VariableDeclarator' && parent.id.name) return parent.id.name
  if (parent && (parent.type === 'Property' || parent.type === 'MethodDefinition') && parent.key) return parent.key.name || '?'
  if (parent && parent.type === 'AssignmentExpression' && parent.left.property) return parent.left.property.name
  return '<anon>'
}

const results = []
function isModuleWrapper(node, parent, grand, great) {
  return parent && parent.type === 'CallExpression' && parent.callee === node
    && grand && grand.type === 'ExpressionStatement' && great && great.type === 'Program'
}

function visit(file, node, parent, grand, great) {
  if (FN.has(node.type) && !isModuleWrapper(node, parent, grand, great)) {
    const lines = node.loc.end.line - node.loc.start.line + 1
    const cx = complexity(node), ne = nesting(node, 0), pa = node.params.length
    const problems = []
    if (lines > MAX_LINES) problems.push(`${lines} lines`)
    if (cx > MAX_COMPLEXITY) problems.push(`complexity ${cx}`)
    if (ne > MAX_NESTING) problems.push(`nesting ${ne}`)
    if (pa > MAX_PARAMS) problems.push(`${pa} parameters`)
    results.push({ file, name: nameOf(node, parent), line: node.loc.start.line, problems })
  }
  children(node).forEach(c => visit(file, c, node, parent, grand))
}

function walkDir(d) {
  return fs.readdirSync(d, { withFileTypes: true }).flatMap(e =>
    e.isDirectory() ? walkDir(path.join(d, e.name)) : e.name.endsWith('.js') ? [path.join(d, e.name)] : [])
}

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const asJson = process.argv.includes('--json')
const targets = process.argv.slice(2).filter(a => !a.startsWith('--'))
const files = (targets.length ? targets.map(t => path.resolve(root, t)) : [path.join(root, 'src', 'ui', 'web')])
  .flatMap(t => fs.statSync(t).isDirectory() ? walkDir(t) : [t])
let total = 0
for (const f of files) {
  const src = fs.readFileSync(f, 'utf8')
  const ast = acorn.parse(src, { ecmaVersion: 'latest', locations: true, allowReturnOutsideFunction: true })
  const before = results.length
  visit(path.relative(root, f).replaceAll('\\', '/'), ast, null)
  total += results.length - before
}
const bad = results.filter(r => r.problems.length)
if (asJson) {
  console.log(JSON.stringify(bad, null, 1))
} else {
  for (const r of bad) console.log(`${r.file}:${r.line} ${r.name}: ${r.problems.join('; ')}`)
  console.log(`\n${bad.length} of ${total} functions break a guardrail`)
}
process.exit(bad.length ? 1 : 0)
