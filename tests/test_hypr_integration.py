"""Hyprland config selection and reversible Lua/Hyprlang integration."""
import contextlib
from dataclasses import replace
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_core import cfg
from waybridge.integration import select_hypr_config,wire_hypr,unwire_hypr
from waybridge.install import user_install,bindings_conf

class HyprIntegrationTests(unittest.TestCase):
    def home(self,root):
        home=Path(root);(home/'.config/hypr').mkdir(parents=True)
        return home,home/'.config/waybridge/config.toml'

    def test_conf_server_has_one_source_after_repeat_and_keeps_user_config(self):
        with tempfile.TemporaryDirectory() as td,patch('pathlib.Path.home',return_value=Path(td)),contextlib.redirect_stdout(io.StringIO()):
            home,config=self.home(td);path=home/'.config/hypr/hyprland.conf'
            original='monitor = ,preferred,auto,1\nsource = ~/.config/hypr/user.conf\n'
            path.write_text(original);c=replace(cfg(home),role='server')
            self.assertEqual(select_hypr_config(config=config),path)
            wire_hypr(c,config);first=path.read_text();wire_hypr(c,config)
            self.assertEqual(path.read_text(),first);self.assertIn(original,first)
            self.assertEqual(first.count('source = ~/.config/bridge/hypr-server.conf'),1)
            self.assertNotIn('dofile',first)
            unwire_hypr(config);self.assertEqual(path.read_text(),original)

    def test_conf_client_role_change_removes_previous_include(self):
        with tempfile.TemporaryDirectory() as td,patch('pathlib.Path.home',return_value=Path(td)),contextlib.redirect_stdout(io.StringIO()):
            home,config=self.home(td);path=home/'.config/hypr/hyprland.conf';path.write_text('# user\n')
            c=cfg(home);wire_hypr(c,config);wire_hypr(replace(c,role='server'),config)
            self.assertNotIn('hypr-client.conf',path.read_text());self.assertIn('hypr-server.conf',path.read_text())

    def test_both_configs_require_explicit_selection_and_remember_it(self):
        with tempfile.TemporaryDirectory() as td,patch('pathlib.Path.home',return_value=Path(td)),contextlib.redirect_stdout(io.StringIO()):
            home,config=self.home(td);lua=home/'.config/hypr/hyprland.lua';conf=lua.with_suffix('.conf')
            lua.write_text('-- user\n');conf.write_text('# user\n')
            with self.assertRaisesRegex(ValueError,'--hypr-config'):select_hypr_config(config=config)
            wire_hypr(cfg(home),config,conf)
            self.assertEqual(select_hypr_config(config=config),conf)
            self.assertEqual(lua.read_text(),'-- user\n')
            wire_hypr(cfg(home),config,lua)
            self.assertNotIn('hypr-client.conf',conf.read_text());self.assertIn('hypr-client.lua',lua.read_text())

    def test_custom_symlink_target_is_updated_without_replacing_link(self):
        with tempfile.TemporaryDirectory() as td,patch('pathlib.Path.home',return_value=Path(td)),contextlib.redirect_stdout(io.StringIO()):
            home,config=self.home(td);target=home/'dotfiles/custom.conf';target.parent.mkdir();target.write_text('# dotfiles\n')
            path=home/'.config/hypr/custom.conf';path.symlink_to(target)
            wire_hypr(replace(cfg(home),role='server'),config,path)
            self.assertTrue(path.is_symlink());self.assertIn('hypr-server.conf',target.read_text())
            self.assertEqual(select_hypr_config(config=config),path)
            unwire_hypr(config);self.assertTrue(path.is_symlink());self.assertEqual(target.read_text(),'# dotfiles\n')
            self.assertTrue(list((home/'.local/state/waybridge/backups').rglob('custom.conf')))

    def test_explicit_missing_or_wrong_format_is_rejected(self):
        with tempfile.TemporaryDirectory() as td,patch('pathlib.Path.home',return_value=Path(td)):
            home,config=self.home(td)
            for path in (home/'missing.conf',home/'config.txt'):
                if path.suffix=='.txt':path.touch()
                with self.assertRaises(ValueError):select_hypr_config(path,config)
            self.assertIsNone(select_hypr_config(config=config))

    def test_server_module_uses_exec_once_without_client_hotkeys_or_lua(self):
        with tempfile.TemporaryDirectory() as td,patch('pathlib.Path.home',return_value=Path(td)),patch('waybridge.install.subprocess.run'),contextlib.redirect_stdout(io.StringIO()):
            home,config=self.home(td)
            with patch.dict('os.environ',{'XDG_RUNTIME_DIR':td}):user_install(replace(cfg(home),role='server'),config)
            bridge=home/'.config/bridge';text=(bridge/'hypr-server.conf').read_text()
            self.assertTrue(text.startswith('exec-once = '));self.assertIn('server-start',text)
            self.assertNotIn('hl.',text);self.assertNotIn('bind = ',text)
            self.assertNotIn('exec-once', (bridge/'hypr-client.conf').read_text())

    def test_conf_client_uses_physical_keys_and_session_hook(self):
        text=bindings_conf(Path('/home/test/config.toml'))
        for code in (52,53,38):self.assertIn('bind = SUPER, code:'+str(code)+', exec, ',text)
        self.assertEqual(text.count('bind = '),3)
        self.assertIn('exec-once = ',text);self.assertIn('session-start',text)
        self.assertIn('permission = /usr/bin/grim, screencopy, allow',text)

class UpdateIntegrationTests(unittest.TestCase):
    def test_update_keeps_conf_selection_and_explicit_stop(self):
        from waybridge.setup import update
        with tempfile.TemporaryDirectory() as td,patch('pathlib.Path.home',return_value=Path(td)),contextlib.redirect_stdout(io.StringIO()):
            home=Path(td);root=home/'.config/hypr';root.mkdir(parents=True)
            conf=root/'hyprland.conf';conf.write_text('# existing user config\n')
            config=home/'.config/waybridge/config.toml';c=replace(cfg(home),role='server');c.state.mkdir();c.stopped.touch()
            with patch('waybridge.install.user_install'),patch('waybridge.control.execute') as control,patch('waybridge.setup.shell_path'),patch('waybridge.setup.run'),patch('waybridge.setup.reload_panel'),patch('waybridge.setup.shutil.which',return_value=None):
                update(c,config)
                first=conf.read_text()
                (root/'hyprland.lua').write_text('-- later unused file\n')
                update(c,config)
            self.assertEqual(conf.read_text(),first)
            self.assertEqual([call.args[1] for call in control.call_args_list],['stop','stop'])
            self.assertTrue(c.stopped.exists());self.assertNotIn('dofile',conf.read_text())
            self.assertEqual((root/'hyprland.lua').read_text(),'-- later unused file\n')

    def test_ambiguous_config_is_rejected_before_wizard_changes_services(self):
        from types import SimpleNamespace
        from waybridge.setup import wizard
        with tempfile.TemporaryDirectory() as td,patch('pathlib.Path.home',return_value=Path(td)),patch.dict('os.environ',{'XDG_RUNTIME_DIR':td}),patch('waybridge.setup.run') as run:
            home=Path(td);root=home/'.config/hypr';root.mkdir(parents=True)
            for suffix in ('.conf','.lua'):(root/('hyprland'+suffix)).write_text('')
            args=SimpleNamespace(config=str(home/'config.toml'),hypr_config=None,no_integrate=False,update=False)
            with self.assertRaisesRegex(ValueError,'--hypr-config'):wizard(args)
            run.assert_not_called()

class AliasAndScopeTests(unittest.TestCase):
    def test_switching_between_symlink_aliases_keeps_selected_include(self):
        with tempfile.TemporaryDirectory() as td,patch('pathlib.Path.home',return_value=Path(td)),contextlib.redirect_stdout(io.StringIO()):
            home=Path(td);root=home/'.config/hypr';root.mkdir(parents=True)
            target=home/'custom.conf';target.write_text('# user\n')
            link=root/'hyprland.conf';link.symlink_to(target)
            config=home/'.config/waybridge/config.toml';c=replace(cfg(home),role='server')
            wire_hypr(c,config,target);wire_hypr(c,config,link)
            self.assertEqual(target.read_text().count('source = ~/.config/bridge/hypr-server.conf'),1)
            self.assertTrue(link.is_symlink())

    def test_cleanup_preserves_unrelated_or_combined_lua_statements(self):
        from waybridge.integration import clean_hypr
        original='dofile("/home/user/.config/bridge/hypr-client.lua.bak")\n'
        original+='dofile("/home/user/.config/bridge/hypr-client.lua"); user_action()\n'
        self.assertEqual(clean_hypr(original,'.lua'),original)
        self.assertEqual(clean_hypr('dofile("/home/user/.config/bridge/hypr-client.lua")\n','.lua'),'')
