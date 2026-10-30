"""Page export validation, native framing, durable delivery and hostile text."""
import base64
from contextlib import redirect_stdout
from dataclasses import replace
from html.parser import HTMLParser
import io
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_core import cfg,png
from waybridge import pages
from waybridge.protocol import frame
from waybridge.receiver import receive


def snapshot(identifier='a'*32):
    return {'format':'waybridge-page/1','scope':'current-section','id':identifier,
        'created_at':'2026-10-28T00:00:00Z',
        'page':{'title':'Sample shuffled form','url':'https://docs.google.com/forms/example',
            'text':'Question\nB\nA',
            'questions':[{'id':'q0001','title':'Question','text':'Question\nB\nA',
                'options':[{'id':'o1','kind':'radio','label':'B','selected':False},
                           {'id':'o2','kind':'radio','label':'A','selected':True}]}],
            'fields':[{'kind':'text','label':'Name','value':'current value','checked':None}],
            'images':[],
            'geometry':{'width':1,'height':1,'scrollX':0,'scrollY':0,'viewportWidth':1,'viewportHeight':1}},
        'tiles':[{'x':0,'y':0,'width':1,'height':1,'png':'data:image/png;base64,'+base64.b64encode(png()).decode()}],
        'warnings':[]}

class PageValidationTests(unittest.TestCase):
    def test_snapshot_retains_shuffled_order_and_current_values(self):
        doc=pages.validate(pages.encode(snapshot()))
        self.assertEqual([o['label'] for o in doc['page']['questions'][0]['options']],['B','A'])
        self.assertTrue(doc['page']['questions'][0]['options'][1]['selected'])
        self.assertEqual(doc['page']['fields'][0]['value'],'current value')
    def test_visual_reference_is_required_and_must_cover_document(self):
        for mutate in (lambda d:d.update(tiles=[]),lambda d:d['tiles'][0].update(y=1),
                       lambda d:d['page']['geometry'].update(height=2),
                       lambda d:d['tiles'][0].update(width=2),
                       lambda d:d['page']['geometry'].update(width=8192,height=100000)):
            doc=snapshot();mutate(doc)
            with self.assertRaises(ValueError):pages.encode(doc)
    def test_rejects_external_resources_malformed_png_and_geometry_types(self):
        for mutate in (lambda d:d['tiles'][0].update(png='https://example.test/track.png'),
                       lambda d:d['tiles'][0].update(png='data:image/png;base64,AAAA'),
                       lambda d:d['tiles'][0].update(x=False),
                       lambda d:d['page']['geometry'].update(width=True),
                       lambda d:d['page']['questions'][0]['options'][0].update(selected='false')):
            doc=snapshot();mutate(doc)
            with self.assertRaises(ValueError):pages.encode(doc)
    def test_renderer_escapes_source_text_and_contains_no_active_source_markup(self):
        doc=snapshot();payload='<script>alert(1)</script><img src="https://evil.test/x">'
        doc['page']['title']=payload;doc['page']['text']=payload
        doc['page']['questions'][0]['title']=payload
        doc['page']['fields'][0]['value']=payload
        result=pages.render(pages.validate(pages.encode(doc))).decode()
        tags=[]
        class Parser(HTMLParser):
            def handle_starttag(self,tag,attrs):tags.append((tag,dict(attrs)))
        Parser().feed(result)
        self.assertFalse(any(tag in {'script','iframe','form','input','object'} for tag,_ in tags))
        self.assertIn('&lt;script&gt;',result)
        self.assertTrue(all(attrs.get('src','').startswith('data:image/png;base64,') for tag,attrs in tags if tag=='img'))
        self.assertIn("default-src 'none'",result)
    def test_limits_and_unknown_fields_rejected(self):
        for doc in ({},[],{**snapshot(),'extra':'not allowed'}, {**snapshot(),'id':'../../x'}):
            with self.assertRaises(ValueError):pages.validate(json.dumps(doc).encode())

class PageReceiverTests(unittest.TestCase):
    def deliver(self,c,doc):
        data=pages.encode(doc);packet,header=frame(doc['id'],data,magic=pages.MAGIC)
        with redirect_stdout(io.StringIO()) as output:receive(c,io.BytesIO(packet))
        return json.loads(output.getvalue()),header
    def test_acked_page_is_durable_readable_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));doc=snapshot()
            ack,header=self.deliver(c,doc);self.assertEqual(ack,{'ok':True,**header})
            folder=c.state/'pages';target=folder/(doc['id']+'.html')
            self.assertIn('Sample shuffled form',target.read_text())
            modified=target.stat().st_mtime_ns
            self.deliver(c,doc);self.assertEqual(target.stat().st_mtime_ns,modified)
            self.assertEqual(len(list(folder.glob('*.html'))),1)
    def test_reused_id_with_different_content_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));doc=snapshot();self.deliver(c,doc)
            doc['page']['title']='different'
            with self.assertRaises(ValueError):self.deliver(c,doc)
    def test_envelope_id_must_match_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            data=pages.encode(snapshot());packet,_=frame('b'*32,data,magic=pages.MAGIC)
            with self.assertRaises(ValueError):receive(cfg(Path(td)),io.BytesIO(packet))
    def test_retention_keeps_ten_snapshots_and_unrelated_files(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));folder=c.state/'pages';folder.mkdir(parents=True)
            unrelated=folder/'notes.html';unrelated.write_text('keep')
            for n in range(12):self.deliver(c,snapshot(f'{n:032x}'))
            self.assertEqual(len(list(folder.glob('*.html'))),11)
            self.assertEqual(unrelated.read_text(),'keep')
            self.assertEqual(json.loads((folder/'latest.json').read_text())['id'],f'{11:032x}')

class PageViewerTests(unittest.TestCase):
    def test_malformed_viewer_metadata_does_not_crash_image_supervisor(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));folder=c.state/'pages';folder.mkdir(parents=True)
            (c.state/'page-viewer.json').write_text('[]')
            (folder/'latest.json').write_text('[]')
            with patch('waybridge.pages.subprocess.run') as opener:pages.PageViewer(c).refresh()
            opener.assert_not_called()

    def test_restart_does_not_open_same_snapshot_again(self):
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));folder=c.state/'pages';folder.mkdir(parents=True)
            (folder/'latest.json').write_text(json.dumps({'id':'a'*32}))
            (folder/('a'*32+'.html')).write_text('fixture')
            with patch('waybridge.pages.subprocess.run',return_value=subprocess.CompletedProcess([],0)) as opener:
                pages.PageViewer(c).refresh()
                pages.PageViewer(c).refresh()
            launches=[call for call in opener.call_args_list if call.args[0][0]=='systemd-run']
            self.assertEqual(len(launches),1)
    def test_failed_open_is_not_recorded_as_success(self):
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));folder=c.state/'pages';folder.mkdir(parents=True)
            (folder/'latest.json').write_text(json.dumps({'id':'a'*32}))
            (folder/('a'*32+'.html')).write_text('fixture')
            with patch('waybridge.pages.subprocess.run',side_effect=[subprocess.CompletedProcess([],3,'inactive',''),subprocess.CalledProcessError(1,['systemd-run'])]),patch('builtins.print'):
                pages.PageViewer(c).refresh()
            self.assertFalse((c.state/'page-viewer.json').exists())

class NativeTests(unittest.TestCase):
    def request(self,c,request):
        data=json.dumps(request).encode();out=io.BytesIO()
        pages.native(c,io.BytesIO(struct.pack('=I',len(data))+data),out)
        result=out.getvalue();size=struct.unpack('=I',result[:4])[0]
        self.assertEqual(len(result)-4,size)
        return json.loads(result[4:])
    def test_native_message_returns_one_framed_ack(self):
        with tempfile.TemporaryDirectory() as td:
            with patch('waybridge.pages.send',return_value={'ok':True,'id':'a'*32}) as send:
                result=self.request(cfg(Path(td)),{'action':'send','snapshot':snapshot()})
            self.assertTrue(result['ok']);send.assert_called_once()
    def test_native_errors_are_framed_not_printed_as_tracebacks(self):
        with tempfile.TemporaryDirectory() as td:
            result=self.request(cfg(Path(td)),{'action':'unexpected'})
            self.assertFalse(result['ok']);self.assertIn('unsupported',result['error'])
            out=io.BytesIO();pages.native(cfg(Path(td)),io.BytesIO(struct.pack('=I',2**31)),out)
            self.assertFalse(json.loads(out.getvalue()[4:])['ok'])
    def test_stop_prevents_launching_transfer(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));c.state.mkdir();c.stopped.touch()
            with patch('waybridge.pages.subprocess.Popen') as process:
                with self.assertRaisesRegex(RuntimeError,r'Win\+X'):pages.send(c,snapshot())
            process.assert_not_called()
    def test_killswitch_cancels_an_inflight_transfer(self):
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));c.state.mkdir()
            with patch('waybridge.pages.subprocess.Popen') as factory:
                proc=factory.return_value
                def waiting(**kwargs):
                    c.stopped.touch()
                    raise subprocess.TimeoutExpired('ssh',.2)
                proc.communicate.side_effect=[waiting, (b'',b'')]
                # First communicate is interrupted with a stop marker in place.
                def communicate(**kwargs):
                    if not c.stopped.exists():return waiting(**kwargs)
                    return b'',b''
                proc.communicate.side_effect=communicate;proc.poll.return_value=None
                with self.assertRaisesRegex(RuntimeError,'отменена'):pages.send(c,snapshot())
                proc.kill.assert_called_once()

if __name__=='__main__':unittest.main()

class AssetUpgradeTests(unittest.TestCase):
    def test_asset_upgrade_resolves_manifest_and_prunes_only_retired_modules(self):
        from waybridge.install import install_page_export
        with tempfile.TemporaryDirectory() as td,patch('pathlib.Path.home',return_value=Path(td)):
            home=Path(td);assets=home/'.local/share/waybridge/firefox-export';assets.mkdir(parents=True)
            for name in ('forms.js','extract.js','section-key.js','personal-note.txt'):(assets/name).write_text('old')
            def write(path,data,mode=0o644):
                path.parent.mkdir(parents=True,exist_ok=True);path.write_text(data)
            install_page_export(cfg(home),home/'config.toml',write)
            manifest=json.loads((assets/'manifest.json').read_text())
            for name in manifest['background']['scripts']:self.assertTrue((assets/name).is_file(),name)
            for name in ('forms.js','extract.js','section-key.js'):self.assertFalse((assets/name).exists())
            self.assertEqual((assets/'personal-note.txt').read_text(),'old')
