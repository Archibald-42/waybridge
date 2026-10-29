"""Regressions for removed input dependencies, readiness and per-transfer ACKs."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from test_core import cfg
from waybridge.config import load
from waybridge.control import start,stop
from waybridge.files import publish_safely
from waybridge.install import unit

class ReadinessTests(unittest.TestCase):
    def test_stop_never_depends_on_network_or_graphical_preflight(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));c.state.mkdir()
            with patch('waybridge.control.preflight',side_effect=RuntimeError('offline')) as probe,patch('waybridge.control.run',return_value=subprocess.CompletedProcess([],0,'','')),patch('waybridge.control.root_unit') as root:
                stop(c)
            probe.assert_not_called();root.assert_called_once_with('stop','bridge-inbox.service');self.assertTrue(c.stopped.exists())
    def test_failed_preflight_does_not_open_endpoint(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));c.state.mkdir()
            with patch('waybridge.control.preflight',side_effect=RuntimeError('no permission')),patch('waybridge.control.stop') as rollback,patch('waybridge.control.root_unit') as root:
                with self.assertRaisesRegex(RuntimeError,'permission'):start(c)
            root.assert_not_called();rollback.assert_not_called();self.assertFalse(c.stopped.exists())
    def test_root_stop_is_attempted_even_if_user_manager_fails(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));c.state.mkdir()
            with patch('waybridge.control.run',side_effect=OSError('manager unavailable')),patch('waybridge.control.root_unit') as root:
                with self.assertRaises(RuntimeError):stop(c)
            root.assert_called_once_with('stop','bridge-inbox.service')
    def test_success_checks_queue_and_only_transport_units(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));c.state.mkdir()
            with patch.dict(os.environ,{'XDG_RUNTIME_DIR':td}),patch('waybridge.control.preflight'),patch('waybridge.control.run',return_value=subprocess.CompletedProcess([],0,'active\n','')),patch('waybridge.control.root_unit') as root,patch('waybridge.control.rpc',return_value={'ok':True}) as ready:
                start(c)
            root.assert_called_once_with('start','bridge-inbox.service');ready.assert_called_once_with(Path(td)/'bridge-shot-queue.sock','status');self.assertFalse(c.stopped.exists())
    def test_file_and_image_units_wait_for_notify(self):
        for command in ('files','gallery'):
            self.assertIn('Type=notify',unit(Path('/tmp/config'),command,ready=True))
    def test_legacy_role_and_user_are_normalized(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'config.toml';p.write_text('role="helper"\nown_ip="100.64.0.1"\npeer_ip="100.64.0.2"\nuser="archi"\nhelper_user="archi"\nkeyboard="/does/not/exist"\n')
            c=load(p);self.assertEqual(c.role,'server');self.assertEqual(c.server_user,'archi');self.assertFalse(hasattr(c,'keyboard'))

class FileConfirmationTests(unittest.TestCase):
    def transaction(self,c,name,data,identifier='a'*32):
        (c.inbox/name).write_bytes(data)
        marker='.delivery-'+identifier+'.json'
        (c.inbox/marker).write_text(json.dumps({'id':identifier,'name':name,'sha256':hashlib.sha256(data).hexdigest()}))
        return marker
    def test_confirmation_correlates_uuid_hash_and_project_write(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));c.inbox.mkdir();c.projects.mkdir()
            marker=self.transaction(c,'main.py',b'print(1)')
            self.assertTrue(publish_safely(c,marker))
            ack=json.loads((c.inbox/'.receipts'/('a'*32+'.json')).read_text())
            self.assertEqual(ack['id'],'a'*32);self.assertTrue(ack['ok']);self.assertEqual(ack['sha256'],hashlib.sha256(b'print(1)').hexdigest())
            self.assertEqual((c.projects/'main.py').read_bytes(),b'print(1)');self.assertFalse((c.inbox/marker).exists())
            marker=self.transaction(c,'main.py',b'new contents','c'*32)
            self.assertTrue(publish_safely(c,marker))
            ack=json.loads((c.inbox/'.receipts'/('c'*32+'.json')).read_text())
            self.assertEqual(ack['sha256'],hashlib.sha256(b'new contents').hexdigest())
    def test_one_broken_destination_does_not_block_other_files(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));c.inbox.mkdir();c.projects.mkdir();(c.projects/'bad.py').mkdir()
            bad=self.transaction(c,'bad.py',b'bad');good=self.transaction(c,'good.py',b'good','b'*32)
            with patch('builtins.print'):
                self.assertFalse(publish_safely(c,bad));self.assertTrue(publish_safely(c,good))
            ack=json.loads((c.inbox/'.receipts'/('a'*32+'.json')).read_text());self.assertFalse(ack['ok'])
            self.assertEqual((c.projects/'good.py').read_bytes(),b'good');self.assertTrue((c.inbox/bad).exists())
    def test_changed_payload_cannot_be_acknowledged(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));c.inbox.mkdir();c.projects.mkdir();marker=self.transaction(c,'main.py',b'original')
            (c.inbox/'main.py').write_bytes(b'changed')
            with patch('builtins.print'):self.assertFalse(publish_safely(c,marker))
            ack=json.loads((c.inbox/'.receipts'/('a'*32+'.json')).read_text());self.assertFalse(ack['ok']);self.assertFalse((c.projects/'main.py').exists())

class IPCTests(unittest.TestCase):
    def test_fragmented_json_response_is_reassembled(self):
        from waybridge.runtime import rpc
        with patch('waybridge.runtime.socket.socket') as factory:
            sock=factory.return_value.__enter__.return_value
            sock.recv.side_effect=[b'{"ok":',b'true,"pending":0}',b'\n']
            self.assertEqual(rpc('/tmp/test.sock','status'),{'ok':True,'pending':0})
    def test_incomplete_response_is_an_explicit_error(self):
        from waybridge.runtime import rpc
        with patch('waybridge.runtime.socket.socket') as factory:
            factory.return_value.__enter__.return_value.recv.side_effect=[b'{"ok":',b'']
            with self.assertRaisesRegex(RuntimeError,'incomplete'):rpc('/tmp/test.sock','status')

if __name__=='__main__':unittest.main()
