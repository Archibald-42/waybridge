"""Hardware-independent regression tests of delivery and fail-safe boundaries."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib
from waybridge.config import Config,load
from waybridge.protocol import frame,parse,verify_ack,validate_png,MAGIC
from waybridge.receiver import receive
from waybridge.screenshots import Budget
from waybridge.files import publish
from waybridge.install import bindings

def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
def png():return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\0\0\0\0'))+chunk(b'IEND',b'')
def cfg(root):
    return Config('client','100.64.0.1','100.64.0.2','archi','archi',root/'inbox',root/'projects',root/'state')

class ProtocolTests(unittest.TestCase):
    def test_verified_roundtrip_and_legacy(self):
        data=png();packet,h=frame('a'*32,data)
        self.assertEqual(parse(io.BytesIO(packet)),(h,data))
        self.assertEqual(parse(io.BytesIO(data)),(None,data))
        self.assertTrue(verify_ack(json.dumps({'ok':True,**h}),h))
        self.assertFalse(verify_ack(json.dumps({'ok':True,**h,'id':'b'*32}),h))
        self.assertFalse(verify_ack(b'[]',h))
    def test_rejects_mutation_truncation_extra_data(self):
        packet,_=frame('a'*32,png())
        for bad in (packet[:-1],packet+b'X',packet[:-1]+b'X'):
            with self.assertRaises(ValueError):parse(io.BytesIO(bad))
        data=bytearray(png());data[45]^=1
        with self.assertRaises(ValueError):validate_png(bytes(data))
    def test_rejects_malformed_header_types_and_limits(self):
        for h in ([],{'id':3},{'id':'a'*32,'sha256':5},{'id':'a'*32,'sha256':'b'*64,'size':True},{'id':'a'*32,'sha256':'b'*64,'size':2**40}):
            with self.subTest(h=h),self.assertRaises(ValueError):parse(io.BytesIO(MAGIC+json.dumps(h).encode()+b'\n'))
    def test_receiver_retry_deduplicates_and_rejects_collision(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));packet,h=frame('a'*32,png())
            with contextlib.redirect_stdout(io.StringIO()) as out:
                receive(c,io.BytesIO(packet));receive(c,io.BytesIO(packet))
            self.assertEqual(len(list(c.shots.glob('*.png'))),1)
            self.assertEqual(len(out.getvalue().splitlines()),2)
            other=chunk(b'tEXt',b'x\0y');data=png()[:-12]+other+png()[-12:]
            bad,_=frame('a'*32,data)
            with self.assertRaises(ValueError):receive(c,io.BytesIO(bad))

class ControlsTests(unittest.TestCase):
    def test_only_transport_hotkeys_remain(self):
        text=bindings(Path('/home/test/config.toml'))
        self.assertEqual(text.count('hl.bind('),3)
        for code in (79,80,81):self.assertIn('code:'+str(code),text)
        for removed in ('code:83','code:84','code:85','ydotool','keyboard'):
            self.assertNotIn(removed,text)

class StorageTests(unittest.TestCase):
    def test_batch_preflight_and_order(self):
        from waybridge.files import push_many
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));a=Path(td)/'first.py';b=Path(td)/'second.txt'
            a.write_text('one');b.write_text('two')
            with patch('waybridge.files.push') as push,contextlib.redirect_stdout(io.StringIO()) as out:
                push_many(c,[a,b]);self.assertEqual([call.args[1].name for call in push.call_args_list],['first.py','second.txt'])
                self.assertIn('first.py',out.getvalue())
            with patch('waybridge.files.push') as push,self.assertRaises(ValueError):push_many(c,[a,Path(td)/'missing.py'])
            push.assert_not_called()
    def test_destination_extension_rejected_before_upload(self):
        from waybridge.files import push
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));source=Path(td)/'source.py';source.write_text('code')
            with self.assertRaises(ValueError):push(c,source,'payload.exe')
    def test_cli_error_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as td:
            result=subprocess.run([sys.executable,'-m','waybridge','--config',str(Path(td)/'missing.toml'),'doctor'],capture_output=True)
            self.assertEqual(result.returncode,1)
            self.assertIn(b'FileNotFoundError:',result.stderr)
            self.assertNotIn(b'Traceback',result.stderr)

    def test_budget_count_and_bytes(self):
        b=Budget(2,100);self.assertTrue(b.reserve());self.assertTrue(b.reserve());self.assertFalse(b.reserve())
        self.assertTrue(b.attach(90));self.assertFalse(b.attach(11));b.release(90);b.release();self.assertEqual(b.status(),{'pending':0,'bytes':0})
    def test_atomic_projection_backups_and_symlink_rejection(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));c.inbox.mkdir();c.projects.mkdir()
            source=c.inbox/'main.py';source.write_text('one');self.assertTrue(publish(c,'main.py'))
            source.write_text('two');self.assertTrue(publish(c,'main.py'))
            self.assertEqual((c.projects/'main.py').read_text(),'two')
            self.assertEqual(len(list((c.state/'versions').iterdir())),1)
            self.assertFalse((c.state/'latest-code').exists())
            (c.inbox/'bad.py').symlink_to(source);self.assertFalse(publish(c,'bad.py'))
            self.assertFalse(publish(c,'../main.py'));self.assertFalse(publish(c,'missing.txt'))
    def test_config_validation(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'config.toml';p.write_text('role="client"\nown_ip="100.64.0.2"\npeer_ip="8.8.8.8"\nuser="archi"\nhelper_user="archi"\n')
            with self.assertRaises(ValueError):load(p)

if __name__=='__main__':unittest.main()
