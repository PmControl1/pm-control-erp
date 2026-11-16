#!/usr/bin/env node
/**
 * Turn a harness run into a short Markdown report: what failed, where, and the
 * server's own log lines for every 5xx the watchdog caught.
 *
 *   node harness/scripts/summarize.mjs [RESULTS_DIR]
 *
 * Reads RESULTS_DIR/results.json (Playwright's JSON reporter) and, when
 * present, RESULTS_DIR/server-logs/app.log (from stack.sh logs). Prints to
 * stdout; CI appends it to the job summary.
 */
import * as fs from 'node:fs';
import * as path from 'node:path';

const dir = process.argv[2] ?? path.join(path.dirname(new URL(import.meta.url).pathname), '..', 'results');
const resultsFile = path.join(dir, 'results.json');
if (!fs.existsSync(resultsFile)) {
  console.log('### Harness\n\nNo results: the tests did not run (see the step log).');
  process.exit(0);
}
const report = JSON.parse(fs.readFileSync(resultsFile, 'utf8'));
const appLogFile = path.join(dir, 'server-logs', 'app.log');
const appLog = fs.existsSync(appLogFile) ? fs.readFileSync(appLogFile, 'utf8').split('\n') : [];

const tests = [];
const walk = (suite, trail) => {
  const here = suite.title ? [...trail, suite.title] : trail;
  for (const spec of suite.specs ?? []) {
    for (const t of spec.tests ?? []) {
      const last = t.results?.at(-1);
      tests.push({ title: [...here.slice(1), spec.title].join(' › '), file: spec.file, line: spec.line, status: last?.status ?? 'skipped', result: last });
    }
  }
  for (const child of suite.suites ?? []) walk(child, here);
};
for (const suite of report.suites ?? []) walk(suite, []);

const failed = tests.filter((t) => t.status === 'failed' || t.status === 'timedOut' || t.status === 'interrupted');
const passed = tests.filter((t) => t.status === 'passed').length;
const skipped = tests.filter((t) => t.status === 'skipped').length;

const out = [];
out.push(`### Harness: ${failed.length ? `${failed.length} failed` : 'all passed'}`);
out.push('');
out.push(`${passed} passed, ${failed.length} failed, ${skipped} skipped. Full report, traces and server logs: the \`harness-report\` artifact.`);

const serverLines = (requestId) => {
  const at = appLog.findIndex((l) => l.includes(`[${requestId}]`));
  if (at < 0) return [];
  const lines = [];
  for (let i = at; i < appLog.length && lines.length < 40; i++) {
    const l = appLog[i];
    // Keep this request's lines and the traceback lines that follow them.
    if (l.includes(`[${requestId}]`) || !/\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d.*\b(INFO|WARNING|ERROR|DEBUG|CRITICAL)\b/.test(l)) lines.push(l);
    else if (lines.length) break;
  }
  return lines;
};

for (const t of failed) {
  out.push('');
  out.push(`#### ✗ ${t.title}`);
  out.push(`\`${t.file}:${t.line}\``);
  const message = (t.result?.errors?.[0]?.message ?? t.result?.error?.message ?? '').replace(/\u001b\[[0-9;]*m/g, '');
  if (message) {
    out.push('```');
    out.push(message.split('\n').slice(0, 15).join('\n'));
    out.push('```');
  }
  // What the page showed when the test failed: Playwright's accessibility
  // snapshot, so a missing button or a wrong screen is visible without the
  // screenshot.
  const context = (t.result?.attachments ?? []).find((a) => a.name === 'error-context' && a.path);
  if (context && fs.existsSync(context.path)) {
    const lines = fs.readFileSync(context.path, 'utf8').split('\n').filter((l) => l.trim() && !l.startsWith('```'));
    out.push('<details><summary>Page at the moment of failure</summary>');
    out.push('');
    out.push('```');
    out.push(lines.slice(0, 80).join('\n'));
    if (lines.length > 80) out.push(`... ${lines.length - 80} more lines in the report`);
    out.push('```');
    out.push('</details>');
  }
  const watchdog = (t.result?.attachments ?? []).find((a) => a.name === 'watchdog' && a.body);
  if (!watchdog) continue;
  const findings = JSON.parse(Buffer.from(watchdog.body, 'base64').toString('utf8'));
  for (const f of findings.filter((x) => x.requestId && x.kind === 'api5xx')) {
    const lines = serverLines(f.requestId);
    out.push(`Server log for \`${f.detail}\` (request \`${f.requestId}\`):`);
    out.push('```');
    out.push(lines.length ? lines.join('\n') : '(no log lines carry this request ID)');
    out.push('```');
  }
}

console.log(out.join('\n'));
