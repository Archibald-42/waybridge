"""Production regressions: outage errors, missed events and repeatable updates."""
from contextlib import ExitStack
from dataclasses import replace
import fcntl
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from test_core import cfg,png
from waybridge.files import push,reconcile,process_event
from waybridge.gallery import Viewer
from waybridge.install import unit
from waybridge.setup import update

class SendingTests(unittest.TestCase):
    def test_stopped_client_error_is_actionable_and_source_is_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));source=Path(td)/'main.py';source.write_text('keep me')
            with patch('waybridge.files.sftp',return_value=subprocess.CompletedProcess([],255,'','Connection refused')) as transfer,patch('waybridge.files.time.sleep'):
                with self.assertRaisesRegex(RuntimeError,'Numpad 7'):push(c,source)
            self.assertEqual(transfer.call_count,3);self.assertEqual(source.read_text(),'keep me')
    def test_bad_host_key_is_not_retried_or_bypassed(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));source=Path(td)/'main.py';source.write_text('keep')
            with patch('waybridge.files.sftp',return_value=subprocess.CompletedProcess([],255,'','Host key verification failed')) as transfer:
                with self.assertRaisesRegex(RuntimeError,'проверку ключей'):push(c,source)
            self.assertEqual(transfer.call_count,1)
    def test_busy_sender_times_out_without_upload(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));c.state.mkdir();source=Path(td)/'main.py';source.write_text('keep')
            with (c.state/'push.lock').open('w') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX)
                with patch('waybridge.files.time.monotonic',side_effect=[0,6]),patch('waybridge.files.sftp') as transfer:
                    with self.assertRaisesRegex(RuntimeError,'Другая отправка'):push(c,source)
                transfer.assert_not_called()
    def test_success_requires_receipt_even_after_successful_upload(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));source=Path(td)/'main.py';source.write_text('keep')
            with patch('waybridge.files.sftp',return_value=subprocess.CompletedProcess([],0,'','')),patch('waybridge.files.wait_receipt',side_effect=RuntimeError('no ACK')):
                with self.assertRaisesRegex(RuntimeError,'no ACK'):push(c,source)

class RecoveryTests(unittest.TestCase):
    def test_scan_recovers_a_missed_event_and_skips_unchanged_file(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));c.inbox.mkdir();c.projects.mkdir();(c.inbox/'main.py').write_text('first')
            seen=reconcile(c,{})
            self.assertEqual((c.projects/'main.py').read_text(),'first')
            with patch('waybridge.files.publish_safely') as publish:
                seen=reconcile(c,seen)
            publish.assert_not_called()
            (c.inbox/'main.py').write_text('second');reconcile(c,seen)
            self.assertEqual((c.projects/'main.py').read_text(),'second')
    def test_scan_does_not_overwrite_local_edits_after_handled_event(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));c.inbox.mkdir();c.projects.mkdir();(c.inbox/'main.py').write_text('incoming')
            seen={};process_event(c,'main.py',seen)
            (c.projects/'main.py').write_text('my local edits')
            reconcile(c,seen)
            self.assertEqual((c.projects/'main.py').read_text(),'my local edits')
    def test_failed_transaction_is_retried_after_fixing_destination(self):
        import hashlib
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));c.inbox.mkdir();c.projects.mkdir();(c.projects/'main.py').mkdir()
            (c.inbox/'main.py').write_bytes(b'code')
            marker=c.inbox/('.delivery-'+'a'*32+'.json')
            marker.write_text(json.dumps({'id':'a'*32,'name':'main.py','sha256':hashlib.sha256(b'code').hexdigest()}))
            with patch('builtins.print'):seen=reconcile(c,{})
            self.assertTrue(marker.exists());(c.projects/'main.py').rmdir()
            reconcile(c,seen)
            self.assertEqual((c.projects/'main.py').read_bytes(),b'code');self.assertFalse(marker.exists())
    def test_gallery_recovers_a_missed_image_event(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));c.state.mkdir();c.shots.mkdir();(c.shots/('a'*32+'.png')).write_bytes(png())
            viewer=Viewer(c);viewer.latest='b'*32+'.png';viewer.started_at=100
            class Alive:
                def poll(self):return None
            viewer.process=Alive()
            with patch.object(viewer,'reconcile') as sync:viewer.refresh(False)
            sync.assert_called_once()
    def test_gallery_does_not_latch_after_three_failures(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));c.state.mkdir();c.shots.mkdir();p=c.shots/('a'*32+'.png');p.write_bytes(png())
            viewer=Viewer(c);viewer.latest=p.name;viewer.attempts=3
            with patch.object(viewer,'start') as start:viewer.refresh(False)
            start.assert_called_once()
    def test_workers_retry_without_systemd_burst_lockout(self):
        text=unit(Path('/tmp/config'),'files',ready=True)
        self.assertIn('StartLimitIntervalSec=0',text);self.assertIn('RestartSec=3',text)

class UpdateTests(unittest.TestCase):
    def test_update_preserves_stopped_state_and_never_calls_sudo(self):
        for running in (False,True):
            with self.subTest(running=running),tempfile.TemporaryDirectory() as td,ExitStack() as stack:
                c=cfg(Path(td));c.state.mkdir()
                if not running:c.stopped.touch()
                calls=stack.enter_context(patch('waybridge.control.execute'))
                stack.enter_context(patch('waybridge.install.user_install'))
                for name in ('shell_path','wire','reload_panel'):stack.enter_context(patch('waybridge.setup.'+name))
                run=stack.enter_context(patch('waybridge.setup.run'))
                stack.enter_context(patch('waybridge.setup.shutil.which',return_value=None));stack.enter_context(patch('builtins.print'))
                update(c,Path(td)/'config.toml')
                self.assertEqual([call.args[1] for call in calls.call_args_list],['stop','start'] if running else ['stop'])
                for call in run.call_args_list:self.assertNotIn('sudo',call.args[0])

if __name__=='__main__':unittest.main()
