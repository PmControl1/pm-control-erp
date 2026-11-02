"""Exercise maintenance failure paths without Docker or any live data."""
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
DOCKER = r'''#!/usr/bin/env python3
import json, os, pathlib, shutil, sys
args = sys.argv[1:]
HEALTHY = '{"status":"healthy","database":"ok"}'
with open(os.environ['MOCK_DOCKER_LOG'], 'a') as out:
    out.write(json.dumps(args) + '\n')
if args[:2] == ['compose', 'ps']:
    print('postgres')
    if os.environ.get('MOCK_APP_RUNNING', '1') == '1': print('app')
if 'pg_dump' in args:
    print('synthetic-pgdump')
if args and args[0] == 'exec' and 'pg_restore' in args:
    sys.stdin.read()
    if os.environ.get('MOCK_FAIL_RESTORE') == '1': sys.exit(17)
if args[:4] == ['compose', 'exec', '-T', 'app'] and 'curl' in args:
    print(os.environ.get('MOCK_APP_HEALTH', HEALTHY))
if args[:4] == ['compose', 'exec', '-T', 'app'] and 'python' in args:
    sys.stdin.read()
    if os.environ.get('MOCK_NO_ADMIN') == '1': sys.exit(28)
if 'psql' in args:
    print('users: 1\nprojects: 1')
if args and args[0] == 'run' and 'restic/restic:0.18.0' in args:
    cmd = args[args.index('restic/restic:0.18.0') + 1:]
    if cmd[0] == 'backup' and os.environ.get('MOCK_FAIL_BACKUP') == '1':
        sys.exit(13)
    if cmd[0] == 'restore':
        target = pathlib.Path(os.environ['RESTORE_TARGET']) / 'backup'
        (target / 'database').mkdir(parents=True)
        (target / 'database' / 'openestimate.dump').write_text('synthetic-pgdump')
        (target / 'files').mkdir()
        (target / 'files' / 'document.txt').write_text('synthetic document')
if 'alpine:3' in args and '/r' in ' '.join(args):
    # Model cleanup of only the script-created restore directory.
    for a in args:
        if a.endswith(':/r'):
            target = pathlib.Path(a[:-3])
            for child in target.iterdir():
                if child.is_dir(): shutil.rmtree(child)
                else: child.unlink()
'''


HEALTHY = '{"status":"healthy","database":"ok"}'
DEGRADED = '{"status":"degraded","database":"error"}'


class MaintenanceScripts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        for name in ['backup.sh', 'restore.sh', 'deploy.sh']:
            shutil.copy2(SCRIPTS / name, self.root / name)
            (self.root / name).chmod(0o700)
        (self.root / '.env').write_text("PMPM_DOMAIN=erp.example.test\nPMPM_IMAGE_TAG=main\nRESTIC_REPOSITORY=s3:https://example.test/bucket\nRESTIC_PASSWORD='synthetic password'\nPOSTGRES_PASSWORD=synthetic\nJWT_SECRET=synthetic\nSMTP_FROM=test@example.test\nBACKUP_STAGING='" + str(self.root / 'staging') + "'\n")
        (self.bin / 'docker').write_text(DOCKER)
        (self.bin / 'curl').write_text('#!/bin/sh\n[ "${MOCK_FAIL_TLS:-0}" != 1 ] || exit 7\nprintf \'%s\\n\' "${MOCK_PUBLIC_HEALTH:-$HEALTHY_JSON}"\n')
        (self.bin / 'sleep').write_text('#!/bin/sh\nexit 0\n')
        for p in self.bin.iterdir(): p.chmod(0o700)
        self.log = self.root / 'docker.jsonl'
        self.env = {**os.environ, 'PATH': str(self.bin) + ':' + os.environ['PATH'], 'MOCK_DOCKER_LOG': str(self.log), 'HEALTHY_JSON': HEALTHY}
        self.env.pop('PMPM_MAINTENANCE_LOCKED', None)

    def run_script(self, name, *args, input='', **env):
        return subprocess.run(['bash', str(self.root / name), *args], env={**self.env, **env}, input=input, text=True, capture_output=True, timeout=20)

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def index(self, words):
        return next(i for i, command in enumerate(self.commands()) if all(word in command for word in words))

    def test_backup_quiesces_writers_and_resumes_before_retention(self):
        result = self.run_script('backup.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(self.index(['compose', 'stop', 'app']), self.index(['pg_dump']))
        self.assertLess(self.index(['pg_dump']), self.index(['restic/restic:0.18.0', 'backup']))
        self.assertLess(self.index(['restic/restic:0.18.0', 'backup']), self.index(['compose', 'start', 'app']))
        self.assertLess(self.index(['compose', 'start', 'app']), self.index(['forget']))
        self.assertEqual((self.root / 'staging' / 'openestimate.dump').stat().st_mode & 0o777, 0o600)

    def test_failed_backup_resumes_app_and_preserves_failure(self):
        result = self.run_script('backup.sh', MOCK_FAIL_BACKUP='1')
        self.assertEqual(result.returncode, 13, result.stderr)
        self.assertIn(['compose', 'start', 'app'], self.commands())
        self.assertNotIn('forget', [part for command in self.commands() for part in command])

    def test_backup_preserves_already_stopped_app(self):
        result = self.run_script('backup.sh', MOCK_APP_RUNNING='0')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(['compose', 'stop', 'app'], self.commands())
        self.assertNotIn(['compose', 'start', 'app'], self.commands())

    def test_second_maintenance_operation_is_rejected(self):
        with open(self.root / '.maintenance.lock', 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_script('backup.sh')
        self.assertEqual(result.returncode, 75)
        self.assertIn('Another backup', result.stderr)
        self.assertEqual(self.commands(), [])

    def test_deploy_can_call_backup_without_deadlock(self):
        result = self.run_script('deploy.sh', 'sha-new')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('PMPM_IMAGE_TAG=sha-new', (self.root / '.env').read_text())
        self.assertLess(self.index(['restic/restic:0.18.0', 'backup']), self.index(['compose', 'pull', 'app']))

    def test_corrupt_restore_never_touches_live_database(self):
        result = self.run_script('restore.sh', input='erp.example.test\n', MOCK_FAIL_RESTORE='1')
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertNotIn(['compose', 'stop', 'app'], self.commands())
        self.assertFalse(any('dropdb' in command for command in self.commands()))
        self.assertTrue(any(command[:2] == ['rm', '-fv'] for command in self.commands()))

    def test_test_restore_uses_only_throwaway_database(self):
        result = self.run_script('restore.sh', '--test')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('RESTORE TEST PASSED', result.stdout)
        for command in self.commands():
            if command[0] == 'exec' and any(client in command for client in ['pg_isready', 'pg_restore', 'psql']):
                self.assertIn('-h', command)
                self.assertEqual(command[command.index('-h') + 1], '127.0.0.1')
        test_start = next(command for command in self.commands() if command[:2] == ['run', '-d'])
        self.assertIn('PGPASSWORD=restore-test', test_start)
        self.assertNotIn(['compose', 'stop', 'app'], self.commands())
        self.assertFalse(any('dropdb' in command for command in self.commands()))

    def test_live_restore_validates_before_replacing_database(self):
        result = self.run_script('restore.sh', input='erp.example.test\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        validation = next(i for i, command in enumerate(self.commands()) if command[0] == 'exec' and 'pg_restore' in command)
        self.assertLess(validation, self.index(['dropdb']))

    def test_fresh_install_never_starts_public_proxy(self):
        result = self.run_script('deploy.sh', MOCK_NO_ADMIN='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(['compose', 'stop', 'caddy'], self.commands())
        self.assertLess(self.index(['compose', 'stop', 'caddy']), self.index(['compose', 'up', '-d', 'postgres', 'app']))
        self.assertNotIn(['compose', 'up', '-d', 'caddy'], self.commands())
        self.assertNotIn(['compose', 'up', '-d'], self.commands())

    def test_deploy_requires_domain_before_docker_actions(self):
        env = self.root / '.env'
        env.write_text(env.read_text().replace('PMPM_DOMAIN=erp.example.test', 'PMPM_DOMAIN='))
        result = self.run_script('deploy.sh')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Set PMPM_DOMAIN', result.stderr)
        self.assertEqual(self.commands(), [])

    def test_invalid_tag_does_not_modify_env(self):
        before = (self.root / '.env').read_text()
        result = self.run_script('deploy.sh', 'bad/tag')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.root / '.env').read_text(), before)
        self.assertEqual(self.commands(), [])

    def test_failed_https_does_not_report_deploy_success_or_persist_tag(self):
        result = self.run_script('deploy.sh', 'sha-new', MOCK_FAIL_TLS='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('PMPM_IMAGE_TAG=main', (self.root / '.env').read_text())
        self.assertNotIn('Open https://', result.stdout)

    # /api/health answers HTTP 200 while it reports "degraded" (database down,
    # module missing, frontend gone), so a 200 alone must never count as up.

    def test_degraded_app_never_starts_public_proxy(self):
        result = self.run_script('deploy.sh', 'sha-new', MOCK_APP_HEALTH=DEGRADED)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('did not report healthy', result.stderr)
        self.assertIn('"database":"error"', result.stderr)
        self.assertNotIn(['compose', 'up', '-d', 'caddy'], self.commands())
        self.assertIn('PMPM_IMAGE_TAG=main', (self.root / '.env').read_text())

    def test_degraded_public_endpoint_does_not_report_success_or_persist_tag(self):
        result = self.run_script('deploy.sh', 'sha-new', MOCK_PUBLIC_HEALTH=DEGRADED)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Last public /api/health: ' + DEGRADED, result.stderr)
        self.assertIn('PMPM_IMAGE_TAG=main', (self.root / '.env').read_text())
        self.assertNotIn('Open https://', result.stdout)

    def test_silent_app_is_not_healthy(self):
        result = self.run_script('deploy.sh', MOCK_APP_HEALTH='')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('<no answer>', result.stderr)
        self.assertNotIn(['compose', 'up', '-d', 'caddy'], self.commands())

    def test_healthy_deploy_reports_the_health_it_saw(self):
        result = self.run_script('deploy.sh', 'sha-new')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"status":"healthy"', result.stdout)
        self.assertIn('Open https://erp.example.test', result.stdout)

    def test_every_app_probe_is_bounded(self):
        self.run_script('deploy.sh')
        probes = [c for c in self.commands() if c[:4] == ['compose', 'exec', '-T', 'app'] and 'curl' in c]
        self.assertTrue(probes)
        for probe in probes:
            self.assertIn('--max-time', probe)


if __name__ == '__main__':
    unittest.main()
