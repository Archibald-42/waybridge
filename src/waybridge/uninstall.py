"""Explicit uninstall with bounded ownership and preserved user documents."""
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import tempfile
import time
from .integration import jsonc,write,reload_panel
from .install import legacy_root_cleanup,q

USER_UNITS=['bridge-key-code','bridge-note','bridge-shot-queue','bridge-files','bridge-shot-view','bridge-start','bridge-kill']
WRAPPERS=['bridge','key-code.py','type-code.py','type-latest.py','bridge-clock.py','note-stream.py','send-answer','battery-link.py','bridge-session-start.sh','shot-send.sh','send-code','push-file.py','shot-queue.py','project-files.py','complete-client-link.py','waybridge','wbs','wb-send','wb-send-as','wb-files']

def system_script(user,uid):
    return '''#!/bin/bash
set -Eeuo pipefail
[[ $EUID == 0 ]] || exit 1
target_user='''+q(user)+'\n'+legacy_root_cleanup(uid)+'''
for name in bridge-inbox bridge-shot bridge-filter; do
 systemctl stop "$name.service" 2>/dev/null || true
 systemctl disable "$name.service" 2>/dev/null || true
 rm -f "/etc/systemd/system/$name.service"
done
if nft list table inet bridge_guard >/dev/null 2>&1; then nft delete table inet bridge_guard; fi
rm -f /etc/polkit-1/rules.d/49-bridge-units.rules
rm -rf /etc/bridge /usr/local/libexec/bridge /run/bridge-input
# Delete only the service account created for our dedicated chroot.
if getent passwd bridge >/dev/null; then
 entry=$(getent passwd bridge)
 [[ $(cut -d: -f6 <<<"$entry") == /inbox && $(cut -d: -f7 <<<"$entry") == /usr/bin/nologin ]] || { echo 'Unexpected bridge account; preserving it'; exit 1; }
 userdel bridge
fi
if getent group bridge-files >/dev/null; then
 gpasswd -d "$target_user" bridge-files 2>/dev/null || true
 if [[ -z $(getent group bridge-files | cut -d: -f4) ]]; then groupdel bridge-files; fi
fi
rm -rf /srv/bridge
systemctl daemon-reload
'''

def run(cfg,yes=False,authorizer='sudo'):
    if os.geteuid()==0:raise RuntimeError('run uninstall as your ordinary user')
    home=Path.home();uid=os.getuid();user=pwd.getpwuid(uid).pw_name
    if not yes:
        print('Удалятся службы, конфигурация и ключи Waybridge. Полученные документы сохранятся.')
        if input('Продолжить? [yes/нет]: ').strip()!='yes':return
    # Authorize before changing live files. pkexec uses a graphical system prompt.
    if authorizer=='sudo':subprocess.run(['sudo','-v'],check=True)
    from .control import execute
    try:execute(cfg,'stop')
    except (OSError,RuntimeError,subprocess.SubprocessError):pass
    subprocess.run(['systemctl','--user','stop',*[name+'.service' for name in USER_UNITS]],capture_output=True,timeout=15)
    preserved=home/'.local/state/waybridge-preserved'/str(time.time_ns())
    for source,name in ((cfg.inbox,'inbox'),(cfg.state/'shots','shots'),(cfg.state/'versions','versions')):
        if source.exists() and any(source.iterdir()):
            preserved.mkdir(parents=True,exist_ok=True)
            shutil.copytree(source,preserved/name,symlinks=True)
    script=system_script(user,uid)
    with tempfile.TemporaryDirectory(prefix='waybridge-uninstall-') as td:
        path=Path(td)/'system.sh';path.write_text(script);path.chmod(0o700)
        subprocess.run(['bash','-n',str(path)],check=True)
        subprocess.run([authorizer,'/usr/bin/bash',str(path)],check=True)
    lua=home/'.config/hypr/hyprland.lua'
    if lua.exists():
        lines=lua.read_text().splitlines(keepends=True)
        write(lua,''.join(line for line in lines if not (any(name in line for name in ('hypr-client.lua','hypr-server.lua','hypr-helper.lua','/.config/bridge/helper-start.lua')) and 'dofile' in line)))
    for bar in (home/'.config/waybar/config.jsonc',home/'.config/waybar/config'):
        if not bar.exists():continue
        data=jsonc(bar.read_text());bars=data if isinstance(data,list) else [data]
        for item in bars:
            for key in ('modules-left','modules-center','modules-right'):
                if key in item:item[key]=[{'custom/bridge-clock':'clock','custom/battery':'battery'}.get(x,x) for x in item[key]]
            item.pop('custom/bridge-clock',None);item.pop('custom/battery',None)
            item.setdefault('clock',{'format':'{:%H:%M}'})
            item.setdefault('battery',{'format':'{capacity}%'})
        write(bar,json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    reload_panel()
    for name in USER_UNITS:(home/'.config/systemd/user'/(name+'.service')).unlink(missing_ok=True)
    for name in WRAPPERS:(home/'.local/bin'/name).unlink(missing_ok=True)
    ssh=home/'.ssh';config=ssh/'config'
    if config.exists():write(config,'\n'.join(line for line in config.read_text().splitlines() if line.strip()!='Include ~/.ssh/bridge.conf')+'\n')
    for pattern in ('bridge-shot','bridge-shot.pub','bridge-inbox','bridge-inbox.pub','bridge.conf','bridge.conf.backup-*','waybridge-known-hosts'):
        for path in ssh.glob(pattern):path.unlink()
    for path in (home/'.config/bridge',home/'.config/waybridge',home/'.local/share/waybridge'):
        if path.is_dir():shutil.rmtree(path)
    if cfg.state in (home/'.cache/bridge',home/'.cache/waybridge') and cfg.state.is_dir():shutil.rmtree(cfg.state)
    (home/'.config/fish/conf.d/waybridge.fish').unlink(missing_ok=True)
    # Other shell source lines are harmless but remove our exact integration line.
    for name in ('.bashrc','.profile','.bash_profile','.zshrc','.zprofile'):
        path=home/name
        if path.exists():write(path,''.join(line for line in path.read_text().splitlines(keepends=True) if line.strip()!='. "$HOME/.config/waybridge/path.sh"'))
    for name in ('bridge-shot-queue.sock','bridge-key-code.sock'):(cfg.runtime/name).unlink(missing_ok=True)
    subprocess.run(['systemctl','--user','daemon-reload'],check=True)
    subprocess.run(['systemctl','--user','reset-failed'],capture_output=True)
    if shutil.which('hyprctl'):subprocess.run(['hyprctl','reload'],capture_output=True)
    print('Waybridge удалён. Документы оставлены в',cfg.projects)
    if preserved.exists():print('Входящие файлы, снимки и версии сохранены в',preserved)
