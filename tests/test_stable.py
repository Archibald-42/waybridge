"""Release regressions for restart safety and untrusted protocol input."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from test_core import cfg
import test_reliability
from waybridge.files import reconcile, publish_safely
from waybridge.runtime import decode_json

class RestartSafetyTests(unittest.TestCase):
    def test_restart_keeps_local_edits_but_new_upload_replaces_them(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));c.inbox.mkdir();c.projects.mkdir()
            source=c.inbox/'main.py';source.write_text('incoming');reconcile(c,{})
            target=c.projects/'main.py';target.write_text('my local edit');reconcile(c,{})
            self.assertEqual(target.read_text(),'my local edit')
            source.write_text('new upload');reconcile(c,{})
            self.assertEqual(target.read_text(),'new upload')
            self.assertIn('my local edit',[p.read_text() for p in (c.state/'versions').iterdir()])
    def test_replayed_completed_marker_keeps_local_edits(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));c.inbox.mkdir();c.projects.mkdir()
            marker=test_reliability.FileConfirmationTests().transaction(c,'main.py',b'incoming');metadata=(c.inbox/marker).read_bytes()
            self.assertTrue(publish_safely(c,marker));(c.projects/'main.py').write_text('local edit')
            (c.inbox/marker).write_bytes(metadata);self.assertTrue(publish_safely(c,marker))
            self.assertEqual((c.projects/'main.py').read_text(),'local edit');self.assertFalse((c.inbox/marker).exists())
    def test_no_success_receipt_if_durable_journal_fails(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));c.inbox.mkdir();c.projects.mkdir();marker=test_reliability.FileConfirmationTests().transaction(c,'main.py',b'incoming')
            with patch('waybridge.files.remember_file',side_effect=OSError('disk full')),contextlib.redirect_stdout(io.StringIO()):self.assertFalse(publish_safely(c,marker))
            ack=json.loads((c.inbox/'.receipts'/('a'*32+'.json')).read_text());self.assertFalse(ack['ok'])
            self.assertTrue((c.inbox/marker).exists());self.assertTrue(publish_safely(c,marker))
    def test_failed_preflight_preserves_explicit_stop(self):
        from waybridge.control import start
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));c.state.mkdir();c.stopped.touch()
            with patch('waybridge.control.preflight',side_effect=RuntimeError('offline')),patch('waybridge.control.stop') as stop:
                with self.assertRaises(RuntimeError):start(c)
            self.assertTrue(c.stopped.exists());stop.assert_not_called()

class InputBoundaryTests(unittest.TestCase):
    def test_ambiguous_nonfinite_and_deep_json_are_rejected(self):
        for value in ('{"id":1,"id":2}','{"value":NaN}','{"value":Infinity}','['*2000+'0'+']'*2000):
            with self.subTest(value=value[:40]),self.assertRaises(ValueError):decode_json(value)
        self.assertEqual(decode_json('{"value":[1,2]}'),{'value':[1,2]})
    def test_receiver_limits_preserve_existing_lower_limit(self):
        import resource
        from waybridge.runtime import receive_limits
        for soft,hard,expected in ((-1,-1,768*1024*1024),(100,200,100),(-1,200,200)):
            with patch('resource.getrlimit',return_value=(soft,hard)),patch('resource.setrlimit') as setter:
                receive_limits();setter.assert_called_once_with(resource.RLIMIT_AS,(expected,hard))
    def test_skip_root_cannot_replace_pinned_peer_key(self):
        from waybridge.setup import apply
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);c=cfg(root);config=root/'config.toml'
            own={'role':c.role,'user':c.user};peer={'ip':c.peer_ip,'user':c.server_user,'auth_key':'new','host_key':'host'}
            (root/'peer-auth.pub').write_text('old');(root/'peer-host.pub').write_text('host')
            with patch('waybridge.setup.run') as run:
                with self.assertRaisesRegex(ValueError,'peer keys'):apply(own,peer,config,c,skip_root=True)
            run.assert_not_called();self.assertFalse(config.exists())
    def test_clean_install_cannot_skip_root(self):
        from waybridge.setup import apply
        with tempfile.TemporaryDirectory() as td,patch('waybridge.setup.run') as run:
            with self.assertRaisesRegex(ValueError,'existing installation'):apply({}, {},Path(td)/'config.toml',None,skip_root=True)
        run.assert_not_called()

class UninstallTests(unittest.TestCase):
    def test_owned_dropins_removed_other_services_and_documents_survive(self):
        from waybridge.uninstall import run
        with tempfile.TemporaryDirectory() as td:
            home=Path(td);c=cfg(home);c.projects.mkdir();(c.projects/'main.py').write_text('keep')
            units=home/'.config/systemd/user';units.mkdir(parents=True)
            for name in ('bridge-files.service.d','unrelated.service.d'):
                (units/name).mkdir();(units/name/'custom.conf').write_text('keep only unrelated')
            (home/'.ssh').mkdir();(home/'.ssh/bridge-admin-known_hosts').write_text('preserve admin pin')
            with patch('pathlib.Path.home',return_value=home),patch('waybridge.uninstall.subprocess.run'),patch('waybridge.uninstall.reload_panel'),patch('waybridge.control.execute'),contextlib.redirect_stdout(io.StringIO()):run(c,yes=True)
            self.assertFalse((units/'bridge-files.service.d').exists());self.assertTrue((units/'unrelated.service.d/custom.conf').exists())
            self.assertEqual((c.projects/'main.py').read_text(),'keep');self.assertTrue((home/'.ssh/bridge-admin-known_hosts').exists())
    def test_account_validated_before_destructive_cleanup(self):
        from waybridge.uninstall import system_script
        script=system_script('archi',1000)
        self.assertLess(script.index('Unexpected bridge account'),script.index('rm -'))
        self.assertIn('rm -rf "/etc/systemd/system/$name.service.d"',script)
        subprocess.run(['bash','-n'],input=script,text=True,check=True)
