// Every child loads the original complete program, preserving all imported
// ambient augmentations. Only semantic diagnostic collection is batched, so
// the checker can release its large type graph between groups of source roots.
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

const root = fileURLToPath(new URL('..', import.meta.url));
const configPath = path.join(root, 'tsconfig.json');
const formatHost = {
  getCanonicalFileName: (file) => file,
  getCurrentDirectory: () => root,
  getNewLine: () => '\n',
};
const report = (diagnostics) => {
  console.error(ts.formatDiagnosticsWithColorAndContext(diagnostics, formatHost));
  process.exit(1);
};
const parsed = ts.getParsedCommandLineOfConfigFile(configPath, {}, {
  ...ts.sys,
  onUnRecoverableConfigFileDiagnostic: (diagnostic) => report([diagnostic]),
});
if (!parsed || parsed.errors.length) report(parsed?.errors ?? []);

const batchSize = 512;
const batchCount = Math.ceil(parsed.fileNames.length / batchSize);
if (process.argv[2] === undefined) {
  for (let batch = 0; batch < batchCount; batch++) {
    console.log(`TypeScript batch ${batch + 1}/${batchCount}: complete program, source roots ${batch * batchSize + 1}-${Math.min((batch + 1) * batchSize, parsed.fileNames.length)}`);
    const result = spawnSync(process.execPath, [
      '--max-old-space-size=5120', fileURLToPath(import.meta.url), String(batch),
    ], { cwd: root, stdio: 'inherit' });
    if (result.error) throw result.error;
    if (result.status !== 0) process.exit(result.status ?? 1);
  }
} else {
  const batch = Number(process.argv[2]);
  if (!Number.isInteger(batch) || batch < 0 || batch >= batchCount) {
    throw new Error(`Invalid TypeScript batch: ${process.argv[2]}`);
  }
  const canonical = (file) => {
    const resolved = path.resolve(file).replaceAll('\\', '/');
    return ts.sys.useCaseSensitiveFileNames ? resolved : resolved.toLowerCase();
  };
  const roots = new Set(parsed.fileNames.map(canonical));
  const assigned = new Set(parsed.fileNames.slice(batch * batchSize, (batch + 1) * batchSize).map(canonical));
  const program = ts.createProgram({
    rootNames: parsed.fileNames,
    options: parsed.options,
    projectReferences: parsed.projectReferences,
  });
  const diagnostics = [
    ...program.getOptionsDiagnostics(),
    ...program.getSyntacticDiagnostics(),
    ...program.getGlobalDiagnostics(),
  ];
  for (const source of program.getSourceFiles()) {
    const name = canonical(source.fileName);
    // Imported implementation files outside tsconfig's roots also need full
    // diagnostics. Declaration dependencies retain tsconfig's skipLibCheck.
    if (assigned.has(name) || !roots.has(name)) {
      diagnostics.push(...program.getSemanticDiagnostics(source));
    }
  }
  if (diagnostics.length) report(diagnostics);
}
