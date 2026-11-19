import * as fs from 'node:fs';
import * as path from 'node:path';
import { HARNESS_DIR } from './env';

/**
 * The files the harness uploads: public samples (samples/manifest.json, fetched
 * by samples/fetch.mjs) and the synthetic edge-case pack (samples/generate.py).
 */
export type Sample = {
  id: string;
  /** The name it is uploaded under. */
  name: string;
  kind: string;
  tier: 'pr' | 'nightly';
  /** Where it is on disk (its name there can differ from `name`). */
  path: string;
  bytes: number;
  sha256: string;
  /** What the upload must do. Public samples are always `accepted`. */
  expect: 'accepted' | 'rejected' | 'either';
  /** `clear`: processing may fail, as long as it ends with a message instead of hanging. */
  outcome?: 'clear';
  notes?: string;
  license?: string;
  source?: string;
  generated?: boolean;
};

/** pr on every pull request; nightly adds the large and slow files. */
export const TIER: 'pr' | 'nightly' = process.env.HARNESS_TIER === 'nightly' ? 'nightly' : 'pr';

function read(file: string): Array<Partial<Sample>> {
  const full = path.join(HARNESS_DIR, '.samples', file);
  if (!fs.existsSync(full)) {
    throw new Error(
      `${full} is missing. Prepare the samples first:\n` +
        `  node harness/samples/fetch.mjs --tier ${TIER}\n  python3 harness/samples/generate.py --tier ${TIER}`,
    );
  }
  return (JSON.parse(fs.readFileSync(full, 'utf8')) as { samples: Array<Partial<Sample>> }).samples;
}

let cached: Sample[] | null = null;

export function allSamples(): Sample[] {
  if (!cached) {
    cached = [...read('index.json'), ...read('generated.json')]
      .map((s) => ({ ...s, expect: s.expect ?? 'accepted' }) as Sample)
      .filter((s) => TIER === 'nightly' || s.tier === 'pr');
  }
  return cached;
}

export function sample(id: string): Sample {
  const found = allSamples().find((s) => s.id === id);
  if (!found) throw new Error(`No sample ${id} in the ${TIER} tier`);
  return found;
}

/** The Documents folder a person would put this file in, as the app names it. */
export type Folder = 'bim_model' | 'dwg_drawing' | 'photo' | 'document';

export function folderFor(s: Sample): Folder {
  if (['ifc', 'rvt'].includes(s.kind)) return 'bim_model';
  if (['dwg', 'dxf'].includes(s.kind)) return 'dwg_drawing';
  if (['jpg', 'jpeg', 'png', 'heic', 'heif', 'webp', 'tif', 'tiff'].includes(s.kind)) return 'photo';
  return 'document';
}

const MIME: Record<string, string> = {
  pdf: 'application/pdf',
  jpg: 'image/jpeg',
  png: 'image/png',
  webp: 'image/webp',
  heic: 'image/heic',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  zip: 'application/zip',
  txt: 'text/plain',
  csv: 'text/csv',
  glb: 'model/gltf-binary',
};

/** What a browser would send as Content-Type; unknown types go as octet-stream. */
export function mimeFor(s: Sample): string {
  return MIME[s.kind] ?? 'application/octet-stream';
}
