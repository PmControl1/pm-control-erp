#!/usr/bin/env node
/**
 * Download the public sample files the harness tests with, and verify them.
 *
 *   node harness/samples/fetch.mjs [--tier pr|nightly]   (default pr; nightly includes pr)
 *
 * Files land in harness/.samples/<id>/<name>, a cache CI keeps between runs;
 * a file already there with the right sha256 is not downloaded again. Every
 * download is checked against the manifest's sha256 and size. An entry whose
 * sha256 is still null is downloaded and its sha256 printed, so it can be
 * pinned in manifest.json; it is used for this run either way.
 *
 * Writes harness/.samples/index.json: the samples that are ready, with their
 * local paths, which the tests read. Exits non-zero if a pinned file is
 * missing or does not match, because a test would then be testing something
 * other than what the manifest promises.
 */
import { createHash } from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { pipeline } from 'node:stream/promises';
import { Readable } from 'node:stream';

const here = path.dirname(new URL(import.meta.url).pathname);
const cache = path.resolve(here, '..', '.samples');
const tierArg = process.argv.includes('--tier') ? process.argv[process.argv.indexOf('--tier') + 1] : 'pr';
const tiers = tierArg === 'nightly' ? ['pr', 'nightly'] : ['pr'];
const { samples } = JSON.parse(fs.readFileSync(path.join(here, 'manifest.json'), 'utf8'));

const sha256 = (file) =>
  new Promise((resolve, reject) => {
    const hash = createHash('sha256');
    fs.createReadStream(file).on('data', (d) => hash.update(d)).on('end', () => resolve(hash.digest('hex'))).on('error', reject);
  });

async function download(url, target) {
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      const response = await fetch(url, { redirect: 'follow', headers: { 'User-Agent': 'pm-control-harness' } });
      if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);
      const partial = `${target}.part`;
      await pipeline(Readable.fromWeb(response.body), fs.createWriteStream(partial));
      fs.renameSync(partial, target);
      return;
    } catch (error) {
      if (attempt === 3) throw error;
      await new Promise((r) => setTimeout(r, 2000 * attempt));
    }
  }
}

const ready = [];
const problems = [];
const unpinned = [];
for (const sample of samples.filter((s) => tiers.includes(s.tier))) {
  const dir = path.join(cache, sample.id);
  const file = path.join(dir, sample.name);
  fs.mkdirSync(dir, { recursive: true });
  try {
    if (!(fs.existsSync(file) && sample.sha256 && (await sha256(file)) === sample.sha256)) {
      process.stdout.write(`↓ ${sample.id} (${sample.bytes ? (sample.bytes / 1e6).toFixed(1) + ' MB' : 'size unknown'}) ... `);
      await download(sample.url, file);
      console.log('done');
    }
    const actual = await sha256(file);
    const size = fs.statSync(file).size;
    if (!sample.sha256) {
      unpinned.push({ id: sample.id, sha256: actual, bytes: size });
    } else if (actual !== sample.sha256 || (sample.bytes && size !== sample.bytes)) {
      problems.push(`${sample.id}: got sha256 ${actual} (${size} bytes), manifest says ${sample.sha256} (${sample.bytes} bytes)`);
      continue;
    }
    ready.push({ ...sample, path: file, bytes: size, sha256: actual });
  } catch (error) {
    problems.push(`${sample.id}: download failed from ${sample.url}: ${error.message}`);
  }
}

fs.writeFileSync(path.join(cache, 'index.json'), JSON.stringify({ tier: tierArg, samples: ready }, null, 2));
console.log(`\n${ready.length} samples ready (${tierArg} tier) in ${cache}`);
for (const u of unpinned) console.log(`::notice::Pin ${u.id} in harness/samples/manifest.json: "sha256": "${u.sha256}", "bytes": ${u.bytes}`);
for (const p of problems) console.log(`::error::${p}`);
process.exit(problems.length ? 1 : 0);
