"""Regression tests for first-shot startup, imv pruning and portable pairing."""
import base64
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from waybridge.gallery import Viewer,images
from waybridge.pairing import validate,read,fingerprint,configuration,public_key
from waybridge.integration import jsonc
from waybridge.control import units,status
from waybridge.receiver import receive
from test_core import cfg,png

KEY='ssh-ed25519 '+base64.b64encode(struct.pack('>I',11)+b'ssh-ed25519'+struct.pack('>I',32)+b'a'*32).decode()
def profile(role='client',ip='100.64.0.2'):
    return {'format':'waybridge-pair/1','role':role,'ip':ip,'user':'tester','hostname':'test-host','auth_key':KEY,'host_key':KEY}

class PairingTests(unittest.TestCase):
    def test_roundtrip_public_only_and_code(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'test.wbpair';path.write_text(json.dumps(profile()))
            self.assertEqual(read(path),profile());self.assertEqual(fingerprint(read(path)),fingerprint(profile()))
    def test_invalid_key_or_extra_private_field_rejected(self):
        for value in ('-----BEGIN OPENSSH PRIVATE KEY-----','ssh-ed25519 aaaa','rsa AAAA'):
            with self.assertRaises(ValueError):public_key(value)
        with self.assertRaises(ValueError):validate({**profile(),'private_key':'never allowed'})
    def test_role_swap_preserves_projects_and_updates_helper_user(self):
        own=profile('helper','100.64.0.1');peer=profile()
        data=configuration(own,peer,{'projects':'/home/test/projects','role':'client'})
        self.assertEqual(data['role'],'helper');self.assertEqual(data['projects'],'/home/test/projects')
        self.assertEqual(data['peer_ip'],'100.64.0.2')
        with self.assertRaises(ValueError):configuration(peer,peer)
    def test_profiles_bounded_and_bad_role_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'bad';p.write_text(' '*16385)
            with self.assertRaises(ValueError):read(p)
        with self.assertRaises(ValueError):validate({**profile(),'role':'root'})
    def test_jsonc_preserves_urls_and_handles_comments_and_trailing_commas(self):
        data=jsonc('''{ // hello
          "url":"https://example.com/*x*/", "list":["clock",], /* ignored */
        }''')
        self.assertEqual(data,{'url':'https://example.com/*x*/','list':['clock']})
    def test_helper_units_and_status_do_not_probe_keyboard(self):
        c=replace(cfg(Path('/tmp')),role='helper')
        self.assertEqual(units(c),(['bridge-shot-view.service'],['bridge-shot.service']))
        with patch('waybridge.control.run',return_value=subprocess.CompletedProcess([],0,'active\n','')):
            value=status(c)
        self.assertNotIn('input',value);self.assertEqual(value['role'],'helper')

class GalleryTests(unittest.TestCase):
    def test_safe_pruning_keeps_imv_selection_in_bounds(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);c=cfg(root);c.state.mkdir();c.shots.mkdir()
            viewer=Viewer(c);viewer.cache=tempfile.TemporaryDirectory(dir=c.state)
            names=['anchor.png','a'*32+'.png','b'*32+'.png','c'*32+'.png']
            for name in names:(Path(viewer.cache.name)/name).write_bytes(png())
            source=c.shots/names[-1];source.write_bytes(png())
            viewer.opened=names.copy();model=names.copy();index=len(model)-1;commands=[]
            def send(text):
                nonlocal index
                commands.append(text)
                if text.startswith('goto '):
                    n=int(text.split()[1]);index=n-1 if n>0 else len(model)+n
                elif text.startswith('close '):
                    n=int(text.split()[1])-1;model.pop(n)
                    # Deliberately model imv 5.0.1: it DOES NOT adjust a later selection.
                    if index==n and index==len(model):index=0
                self.assertLess(index,len(model),text)
            viewer.message=send;viewer.reconcile([source])
            self.assertEqual(commands[0],'goto 1');self.assertEqual(commands[-1],'goto -1')
            self.assertEqual(viewer.opened,['anchor.png',source.name]);viewer.close()
    def test_receiver_retention_cannot_remove_viewer_hardlink(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));c.state.mkdir();c.shots.mkdir();source=c.shots/('a'*32+'.png');source.write_bytes(png())
            viewer=Viewer(c);viewer.cache=tempfile.TemporaryDirectory(dir=c.state)
            link=viewer.link(source);source.unlink();self.assertEqual(link.read_bytes(),png());viewer.close()
    def test_crashed_viewer_schedules_retry_without_new_image(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));c.state.mkdir();c.shots.mkdir();p=c.shots/('a'*32+'.png');p.write_bytes(png())
            viewer=Viewer(c);viewer.latest=p.name;viewer.attempts=1
            class Dead:
                pid=1;returncode=-11
                def poll(self):return -11
            viewer.process=Dead()
            with patch('waybridge.gallery.time.monotonic',return_value=10):viewer.refresh(False)
            self.assertIsNone(viewer.process);self.assertFalse(viewer.dismissed)
            with patch('waybridge.gallery.time.monotonic',return_value=11),patch.object(viewer,'start') as start:viewer.refresh(False)
            start.assert_called_once();self.assertEqual(viewer.attempts,2)
    def test_clean_close_waits_for_next_image(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td));c.state.mkdir();c.shots.mkdir();p=c.shots/('a'*32+'.png');p.write_bytes(png())
            viewer=Viewer(c);viewer.latest=p.name
            class Closed:
                pid=1;returncode=0
                def poll(self):return 0
            viewer.process=Closed();viewer.refresh(False);self.assertTrue(viewer.dismissed)
            with patch.object(viewer,'start') as start:viewer.refresh(False)
            start.assert_not_called()
    def test_images_ignore_symlinks_and_cap_history(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for i in range(55):(root/(f'{i:032x}'+'.png')).write_bytes(png())
            (root/('f'*32+'.png')).symlink_to(root/('0'*32+'.png'))
            self.assertEqual(len(images(root)),50);self.assertNotIn(root/('f'*32+'.png'),images(root))
    def test_health_request_is_authenticated_transport_without_image_write(self):
        with tempfile.TemporaryDirectory() as td:
            c=cfg(Path(td))
            with patch('waybridge.diagnostics.helper_health',return_value={'ok':True,'protocol':'WB1'}),patch('sys.stdout',new_callable=io.StringIO) as output:
                receive(c,io.BytesIO(b'WBH1\n'))
            self.assertEqual(json.loads(output.getvalue())['protocol'],'WB1');self.assertFalse(c.shots.exists())


class InstallerTests(unittest.TestCase):
    def test_upgrade_removes_legacy_units_and_keeps_project_documents(self):
        from waybridge.install import user_install
        with tempfile.TemporaryDirectory() as td:
            home=Path(td);c=cfg(home);c.inbox.mkdir();c.projects.mkdir();c.state.mkdir()
            user=home/'.config/systemd/user';user.mkdir(parents=True)
            for name in ('bridge-key-code.service','bridge-note.service'):(user/name).write_text('old')
            (c.inbox/'clock.txt').write_text('03:42');(c.projects/'main.py').write_text('keep')
            with patch('pathlib.Path.home',return_value=home),patch.dict(os.environ,{'XDG_RUNTIME_DIR':td}),patch('waybridge.install.subprocess.run'),patch('sys.stdout',new_callable=io.StringIO):
                user_install(c,home/'config.toml')
            self.assertFalse((user/'bridge-key-code.service').exists());self.assertFalse((user/'bridge-note.service').exists())
            self.assertTrue((user/'bridge-shot-queue.service').exists());self.assertTrue((user/'bridge-files.service').exists())
            self.assertEqual((c.projects/'main.py').read_text(),'keep');self.assertFalse((c.inbox/'clock.txt').exists())
            (c.inbox/'clock.txt').write_text('ordinary received document')
            with patch('pathlib.Path.home',return_value=home),patch.dict(os.environ,{'XDG_RUNTIME_DIR':td}),patch('waybridge.install.subprocess.run'),patch('sys.stdout',new_callable=io.StringIO):
                user_install(c,home/'config.toml')
            self.assertEqual((c.inbox/'clock.txt').read_text(),'ordinary received document')
    def test_uninstall_system_scope_and_bash_syntax(self):
        from waybridge.uninstall import system_script
        script=system_script('tester',1000)
        self.assertIn('nft delete table inet bridge_guard',script)
        self.assertNotIn('flush ruleset',script);self.assertNotIn('rm -rf /home',script)
        self.assertNotIn('stop tailscale',script);self.assertNotIn('rm -rf /etc/ssh',script)
        self.assertIn('userdel bridge',script)
        subprocess.run(['bash','-n'],input=script,text=True,check=True)
    def test_role_plans_stop_old_endpoints_and_reload_firewall(self):
        from waybridge.install import root_plan
        for role in ('client','helper'):
            with self.subTest(role=role),tempfile.TemporaryDirectory() as td:
                root=Path(td);c=replace(cfg(root),role=role,inbox=Path('/srv/bridge/inbox'))
                key=root/'peer.pub';key.write_text(KEY+'\n');plan=root/'plan.sh'
                with patch('waybridge.install.subprocess.run'),patch('waybridge.install.subprocess.check_output',side_effect=['ATTRS{name}=="Test keyboard"\n','/devices/platform/test/input/input1/event0\n']),patch('sys.stdout',new_callable=io.StringIO):
                    root_plan(c,root/'config.toml',key,plan)
                text=plan.read_text()
                self.assertIn('for unit in bridge-inbox.service ydotool-bridge.service bridge-shot.service',text)
                self.assertIn('systemctl restart bridge-filter.service',text)
                self.assertIn('rm -f /etc/systemd/system/ydotool-bridge.service',text)
                self.assertNotIn('ydotoold --socket',text)
                self.assertNotIn('RUN+=',text)
                self.assertIn('systemctl disable bridge-shot.service' if role=='client' else 'systemctl disable bridge-inbox.service',text)
                subprocess.run(['bash','-n',str(plan)],check=True)
    def test_integration_idempotent_and_role_change_restores_real_modules(self):
        from waybridge.integration import wire
        with tempfile.TemporaryDirectory() as td:
            home=Path(td);lua=home/'.config/hypr/hyprland.lua';lua.parent.mkdir(parents=True);lua.write_text('-- user config\ndofile("/home/test/.config/bridge/helper-start.lua")\n')
            bar=home/'.config/waybar/config.jsonc';bar.parent.mkdir(parents=True);bar.write_text('{"modules-center":["clock"],"modules-right":["battery"]}')
            c=cfg(home)
            with patch('pathlib.Path.home',return_value=home),patch('sys.stdout',new_callable=io.StringIO):
                wire(c,home/'config.toml');wire(c,home/'config.toml')
                self.assertEqual(lua.read_text().count('hypr-client.lua'),1)
                self.assertNotIn('helper-start.lua',lua.read_text())
                self.assertEqual(json.loads(bar.read_text())['modules-center'],['clock'])
                self.assertEqual(json.loads(bar.read_text())['modules-right'],['custom/battery'])
                wire(replace(c,role='helper'),home/'config.toml')
                self.assertEqual(json.loads(bar.read_text())['modules-center'],['clock'])
                self.assertEqual(json.loads(bar.read_text())['modules-right'],['battery'])

class ShellTests(unittest.TestCase):
    def test_fish_path_install_is_repeatable_and_keeps_system_bridge(self):
        from types import SimpleNamespace
        from waybridge.integration import shell_path
        with tempfile.TemporaryDirectory() as td,patch('pathlib.Path.home',return_value=Path(td)),patch('pwd.getpwuid',return_value=SimpleNamespace(pw_shell='/bin/fish')),patch('sys.stdout',new_callable=io.StringIO):
            shell_path();first=(Path(td)/'.config/fish/conf.d/waybridge.fish').read_text()
            shell_path();self.assertEqual((Path(td)/'.config/fish/conf.d/waybridge.fish').read_text(),first)
            self.assertIn('set -gx PATH $PATH',first)

class BootstrapTests(unittest.TestCase):
    def test_python_and_cli_load_same_current_version(self):
        import sys
        with tempfile.TemporaryDirectory() as td:
            prefix=Path(td)/'venv';project=Path(__file__).resolve().parents[1]
            subprocess.run([sys.executable,str(project/'scripts/bootstrap.py'),'--prefix',str(prefix)],check=True,capture_output=True)
            result=subprocess.run([str(prefix/'bin/python'),'-c','import waybridge; print(waybridge.__version__)'],capture_output=True,text=True,check=True)
            from waybridge import __version__
            self.assertEqual(result.stdout.strip(),__version__)
            help_result=subprocess.run([str(prefix/'bin/waybridge'),'setup','--help'],capture_output=True,text=True,check=True)
            self.assertIn('--peer-profile',help_result.stdout)
            self.assertNotIn('--keyboard',help_result.stdout)
            cli=subprocess.run([str(prefix/'bin/waybridge'),'--help'],capture_output=True,text=True,check=True).stdout
            for removed in ('send-answer','release','notes','clock,','input,'):self.assertNotIn(removed,cli)
            self.assertFalse((project/'src/waybridge/keyboard.py').exists());self.assertFalse((project/'src/waybridge/inject.py').exists())

if __name__=='__main__':unittest.main()
