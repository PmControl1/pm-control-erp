// PM Project Management - how a spreadsheet was read, as the import preview says it.
// Licensed under the GNU AGPL v3.0 or later, like the rest of this program.
/**
 * The reading the server made of a spreadsheet (`metadata.reading` of the
 * preview), and the words the preview says it in.
 *
 * Every workbook is read with a recipe: which sheets, rows and columns hold the
 * bill, and which cell holds its total. The recipe came from the heading rules,
 * from a layout saved when an earlier file of the same layout was imported, or
 * from the workspace AI. A recipe the rules did not write is sent back with
 * every re-preview and with the import, so a change of columns re-reads the
 * same layout, the AI is not asked twice, and the bill imported is the bill
 * previewed.
 */

/** Minimal shape of the i18next `t` used here (repo convention). */
type Translate = (key: string, opts?: Record<string, unknown>) => string;

export type ReadingSource = 'rules' | 'saved' | 'ai' | 'preview' | 'person';

export interface ReadingCheck {
  lines: number;
  priced: number;
  value_only: number;
  /** What the file writes in its value column on the lines read. */
  values_sum: number | null;
  /** Quantity times unit price over the lines as imported. */
  imported_sum: number;
  file_total: number | null;
  file_total_cell?: string | null;
  total_matches: boolean | null;
  mismatch_count: number;
  currency?: string;
  ok: boolean;
}

export interface Reading {
  source: ReadingSource;
  recipe?: Record<string, unknown>;
  check?: ReadingCheck;
  saved_from?: string;
}

/** The reading of a preview's metadata, or `null` for a file read without one (GAEB, CSV, a PDF). */
export function readingOf(metadata: Record<string, unknown> | undefined): Reading | null {
  const reading = metadata?.reading;
  if (!reading || typeof reading !== 'object') return null;
  const source = (reading as { source?: unknown }).source;
  if (typeof source !== 'string') return null;
  return reading as Reading;
}

/**
 * The recipe to send back with the next preview and the import, as the `recipe`
 * form field. A reading by the heading rules is not sent: the server reads the
 * file by its headings again, the same way, and a changed column is laid over
 * that reading as it always was.
 */
export function recipeField(reading: Reading | null): string | null {
  if (!reading?.recipe || reading.source === 'rules') return null;
  return JSON.stringify(reading.recipe);
}

/** Who worked out where the bill is in the file. */
export function readingSourceText(reading: Reading, t: Translate): string {
  switch (reading.source) {
    case 'ai':
      return t('boq.import_reading.source_ai', {
        defaultValue: 'The workspace AI worked out which rows and columns hold the bill',
      });
    case 'saved':
      return reading.saved_from
        ? t('boq.import_reading.source_saved_from', {
            defaultValue: 'Read like {{file}}, imported earlier with the same layout',
            file: reading.saved_from,
          })
        : t('boq.import_reading.source_saved', {
            defaultValue: 'Read like an earlier file with the same layout',
          });
    case 'person':
      return t('boq.import_reading.source_person', { defaultValue: 'Read with the columns you chose' });
    case 'preview':
      return t('boq.import_reading.source_preview', { defaultValue: 'Read as previewed' });
    default:
      return t('boq.import_reading.source_rules', { defaultValue: 'Read by its column headings' });
  }
}

/**
 * How the values read stand against the file's own total, or `null` when there
 * is nothing to compare: a bill without prices, or a file without a total.
 */
export function totalCheckText(
  check: ReadingCheck,
  t: Translate,
  formatNumber: (v: number) => string,
): { text: string; ok: boolean } | null {
  if (check.file_total == null) return null;
  const sum = check.values_sum ?? check.imported_sum;
  if (check.total_matches) {
    return {
      ok: true,
      text: check.file_total_cell
        ? t('boq.import_reading.total_matches_cell', {
            defaultValue: 'The lines add up to {{sum}}, the total in cell {{cell}} of the file',
            sum: formatNumber(sum),
            cell: check.file_total_cell,
          })
        : t('boq.import_reading.total_matches', {
            defaultValue: "The lines add up to {{sum}}, the file's total",
            sum: formatNumber(sum),
          }),
    };
  }
  return {
    ok: false,
    text: t('boq.import_reading.total_differs', {
      defaultValue: "The lines add up to {{sum}}, but the file's total is {{total}}. Check the rows and columns read",
      sum: formatNumber(sum),
      total: formatNumber(check.file_total),
    }),
  };
}

/** What the import makes of the lines whose value is not quantity × unit price, and of value-only lines. */
export function checkNotes(check: ReadingCheck, t: Translate, formatNumber: (v: number) => string): string[] {
  const notes: string[] = [];
  if (check.mismatch_count > 0) {
    notes.push(
      t('boq.import_reading.mismatches', {
        defaultValue:
          '{{count}} line(s) give a value that is not quantity × unit price; imported as written, so the bill comes to {{imported}}. They are listed in the warnings',
        count: check.mismatch_count,
        imported: formatNumber(check.imported_sum),
      }),
    );
  }
  if (check.value_only > 0) {
    notes.push(
      t('boq.import_reading.value_only', {
        defaultValue: '{{count}} line(s) give only a value: each is imported as a lump sum, 1 × the value',
        count: check.value_only,
      }),
    );
  }
  return notes;
}

/** `"B"` for column index 1: the letter a spreadsheet shows above the column. */
export function columnLetter(index: number): string {
  let letters = '';
  let n = index + 1;
  while (n > 0) {
    const r = (n - 1) % 26;
    letters = String.fromCharCode(65 + r) + letters;
    n = Math.floor((n - 1) / 26);
  }
  return letters;
}
