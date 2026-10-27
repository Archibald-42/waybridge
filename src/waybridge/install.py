"""Reviewable installers. No hidden downloads, automatic arming or secret material."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
from .runtime import atomic

def q(value):return shlex.quote(str(value))
def executable():return Path(sys.executable).parent/'waybridge'
def command(config,args):return q(executable())+' --config '+q(config)+' '+args

def unit(config,args,watchdog=False):
    return '''[Unit]
Description=Waybridge '''+args+'''
PartOf=graphical-session.target
StartLimitIntervalSec=60
StartLimitBurst=3

[Service]
Type='''+('notify' if watchdog else 'simple')+'\nExecStart='+command(config,args)+'''
Restart=on-failure
RestartSec=2
TimeoutStartSec=10
TimeoutStopSec=3
KillMode=control-group
UMask=0077
NoNewPrivileges=yes
MemoryMax=384M
LimitCORE=0
'''+('WatchdogSec=4\nWatchdogSignal=SIGKILL\nNotifyAccess=main\n' if watchdog else '')

def bindings(config):
    lines=['-- Waybridge: physical Numpad keycodes; NumLock-independent.']
    for code,action in [(79,'start'),(80,'shot'),(81,'kill')]:
        down=command(config,'trigger '+action+' down')
        lines.append('hl.bind('+json.dumps(' + code:'+str(code))+', hl.dsp.exec_cmd('+json.dumps(down)+'))')
    lines+=['hl.permission("/usr/bin/grim", "screencopy", "allow")',
            'hl.on("hyprland.start", function() hl.exec_cmd('+json.dumps(command(config,'session-start'))+') end)']
    return '\n'.join(lines)+'\n'

def legacy_root_cleanup(uid):
    """Remove only the old Waybridge input capability, retaining transport."""
    return '''systemctl stop ydotool-bridge.service 2>/dev/null || true
systemctl disable ydotool-bridge.service 2>/dev/null || true
python - <<'WAYBRIDGE_CLEANUP'
from pathlib import Path
import glob,re,subprocess
rule=Path('/etc/udev/rules.d/90-bridge-key-code.rules')
if rule.exists():
    text=rule.read_text()
    scope=re.search(r'DEVPATH=="([^"]+)"',text)
    if scope:
        for sys in glob.glob('/sys'+scope[1]):
            device=Path('/dev/input')/Path(sys).name
            if device.exists():subprocess.run(['setfacl','-x','u:UID_VALUE',str(device)],check=True)
    rule.unlink()
WAYBRIDGE_CLEANUP
rm -f /etc/systemd/system/ydotool-bridge.service
udevadm control --reload-rules
if getent group bridge-input >/dev/null; then
 gpasswd -d "$target_user" bridge-input 2>/dev/null || true
 if [[ -z $(getent group bridge-input | cut -d: -f4) ]]; then groupdel bridge-input; fi
fi
'''.replace('UID_VALUE',str(uid))

def cleanup_user(cfg):
    """Delete retired entrypoints and units; preserve incoming user documents."""
    home=Path.home()
    legacy=any((home/'.config/systemd/user'/name).exists() for name in ('bridge-key-code.service','bridge-note.service'))
    subprocess.run(['systemctl','--user','stop','bridge-key-code.service','bridge-note.service'],capture_output=True,timeout=8)
    for name in ('bridge-key-code.service','bridge-note.service'):
        (home/'.config/systemd/user'/name).unlink(missing_ok=True)
    for name in ('key-code.py','type-code.py','type-latest.py','bridge-clock.py','note-stream.py','send-answer'):
        (home/'.local/bin'/name).unlink(missing_ok=True)
    for name in ('note-waybar.jsonc','note-waybar.css','waybar-modules.json'):
        (home/'.config/bridge'/name).unlink(missing_ok=True)
    for name in ('latest-code','clock-hidden','input-state.json'):
        (cfg.state/name).unlink(missing_ok=True)
    for name in ('bridge-key-code.sock','waybridge-hold-input','waybridge-hold-reset','waybridge-hold-clock'):
        (cfg.runtime/name).unlink(missing_ok=True)
    # Obsolete control files are never project documents; regular delivery remains.
    if legacy:
        for name in ('clock.txt','clock.json','answer.txt'):
            (cfg.inbox/name).unlink(missing_ok=True)

def user_install(cfg,config):
    home=Path.home();backup=home/'.local/state/waybridge/backups'/time.strftime('%Y%m%d-%H%M%S')
    def write(path,data,mode=0o644):
        path=Path(path)
        if path.exists():
            dest=backup/path.relative_to(home);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,dest)
        atomic(path,data.encode());path.chmod(mode)
    cleanup_user(cfg)
    wrappers={'bridge':'control','shot-send.sh':'shot request','battery-link.py':'battery','bridge-session-start.sh':'session-start','send-code':'send-code','push-file.py':'send-code'}
    if cfg.role=='helper':wrappers={k:v for k,v in wrappers.items() if k in {'bridge','send-code','push-file.py'}}
    else:wrappers={k:v for k,v in wrappers.items() if k not in {'send-code','push-file.py'}}
    for name,args in wrappers.items():
        write(home/'.local/bin'/name,'#!/bin/sh\nexec '+command(config,args)+' "$@"\n',0o755)
    units=home/'.config/systemd/user'
    if cfg.role=='client':
        for name,args,wd in [('bridge-shot-queue','shot serve',True),('bridge-files','files',False)]:
            text=unit(config,args,wd)
            write(units/(name+'.service'),text)
        for name,action in [('bridge-start','start'),('bridge-kill','stop')]:
            write(units/(name+'.service'),'[Unit]\nDescription=Waybridge '+action+'\n[Service]\nType=oneshot\nTimeoutStartSec=45\nExecStart='+command(config,'control '+action)+'\n')
        write(home/'.config/bridge/hypr-helper.lua','-- Helper startup disabled: this device is now a client.\n')
        bridge=home/'.config/bridge';bridge.mkdir(parents=True,exist_ok=True)
        write(bridge/'hypr-client.lua',bindings(config))
    else:
        write(units/'bridge-shot-view.service',unit(config,'gallery'))
        write(home/'.config/bridge/hypr-client.lua','-- Client controls disabled: this device is now a helper.\n')
        write(home/'.config/bridge/hypr-helper.lua','hl.on(\"hyprland.start\", function() hl.exec_cmd('+json.dumps(command(config,'helper-start'))+') end)\n')
    subprocess.run(['systemctl','--user','daemon-reload'],check=True,timeout=5)
    print('Installed user files. Backup:',backup)
    print('Client module:',home/'.config/bridge/hypr-client.lua')
    print('Installed screenshot and file transport. No service was started.')

def root_plan(cfg,config,keyfile,output):
    if str(cfg.inbox)!='/srv/bridge/inbox':raise ValueError('root installer requires /srv/bridge/inbox')
    subprocess.run(['ssh-keygen','-l','-f',str(keyfile)],check=True,capture_output=True)
    lines=[x.split() for x in keyfile.read_text().splitlines() if x.strip()]
    if len(lines)!=1 or len(lines[0])<2 or lines[0][0]!='ssh-ed25519':raise ValueError('one Ed25519 PUBLIC key required')
    key=' '.join(lines[0][:2]);uid=os.getuid();home=Path.home();port=2222 if cfg.role=='client' else 2223
    account='bridge' if cfg.role=='client' else cfg.user
    text='''#!/usr/bin/env bash
# Generated from validated local config. Review before sudo.
set -Eeuo pipefail
[[ $EUID == 0 ]] || { echo 'Run with sudo'; exit 1; }
'''
    text+='target_user='+q(cfg.user)+'\ntarget_uid='+str(uid)+'\n'
    text+='[[ $(id -u "$target_user") == "$target_uid" ]] || exit 1\n'
    text+='[[ $(tailscale ip -4) == '+q(cfg.own_ip)+' ]] || { echo "Tailscale IP changed"; exit 1; }\n'
    dependencies='openssh nftables python inotify-tools '+('acl grim' if cfg.role=='client' else 'imv')
    text+='pacman -S --needed --noconfirm '+dependencies+'\n'
    text+='for unit in bridge-inbox.service ydotool-bridge.service bridge-shot.service; do systemctl stop \"$unit\" 2>/dev/null || true; done\n'
    if cfg.role=='client':text+='systemctl disable bridge-shot.service 2>/dev/null || true\n'
    else:text+='systemctl disable bridge-inbox.service ydotool-bridge.service 2>/dev/null || true\n'
    text+='backup=/var/lib/waybridge/backups/$(date +%Y%m%d-%H%M%S)\ninstall -d -m 700 \"$backup\"\nfor path in /etc/bridge /etc/systemd/system/bridge-inbox.service /etc/systemd/system/bridge-shot.service /etc/systemd/system/bridge-filter.service /etc/systemd/system/ydotool-bridge.service /etc/udev/rules.d/90-bridge-key-code.rules /etc/polkit-1/rules.d/49-bridge-units.rules /usr/local/libexec/bridge/receive-shot.py; do\n if [[ -e $path ]]; then cp -a --parents \"$path\" \"$backup\"; fi\ndone\n'
    text+=legacy_root_cleanup(uid)
    text+='install -d -o root -g root -m 755 /etc/bridge /etc/bridge/keys /usr/local/libexec/bridge\nssh-keygen -A\n'
    def put(path,data,mode=644):
        nonlocal text
        text+='cat > '+q(path)+" <<'WAYBRIDGE_FILE'\n"+data+'\nWAYBRIDGE_FILE\nchmod '+str(mode)+' '+q(path)+'\nchown root:root '+q(path)+'\n'
    if cfg.role=='client':
        text+='''getent group bridge-files >/dev/null || groupadd bridge-files
if ! id bridge >/dev/null 2>&1; then useradd -M -g bridge-files -d /inbox -s /usr/bin/nologin bridge; fi
[[ $(getent passwd bridge | cut -d: -f6) == /inbox ]] || exit 1
usermod -aG bridge-files "$target_user"
install -d -o root -g root -m 755 /srv/bridge
install -d -o bridge -g bridge-files -m 2770 /srv/bridge/inbox
setfacl -m "u:$target_uid:rwx,d:u:$target_uid:rwx,d:m:rwx" /srv/bridge/inbox
'''
        put('/etc/polkit-1/rules.d/49-bridge-units.rules','''polkit.addRule(function(action, subject) {
    if (action.id === "org.freedesktop.systemd1.manage-units" && subject.user === '''+json.dumps(cfg.user)+''') {
        var unit = action.lookup("unit"), verb = action.lookup("verb");
        if (unit === "bridge-inbox.service" && (verb === "start" || verb === "stop")) return polkit.Result.YES;
    }
});''')
    else:
        put('/etc/polkit-1/rules.d/49-bridge-units.rules','polkit.addRule(function(action, subject) { if (action.id === \"org.freedesktop.systemd1.manage-units\" && subject.user === '+json.dumps(cfg.user)+' && action.lookup(\"unit\") === \"bridge-shot.service\" && (action.lookup(\"verb\") === \"start\" || action.lookup(\"verb\") === \"stop\")) return polkit.Result.YES; });')
        put('/usr/local/libexec/bridge/receive-shot.py','#!/bin/sh\nexec '+command(config,'receive'),755)
    auth='restrict,from="'+cfg.peer_ip+'" '+key
    put('/etc/bridge/keys/'+account,auth)
    ssh=f'''Port {port}
AddressFamily inet
ListenAddress {cfg.own_ip}
HostKey /etc/ssh/ssh_host_ed25519_key
PidFile /run/bridge-{cfg.role}.pid
UsePAM yes
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
AuthenticationMethods publickey
AllowUsers {account}
AuthorizedKeysFile /etc/bridge/keys/%u
StrictModes yes
DisableForwarding yes
PermitTTY no
PermitUserRC no
MaxAuthTries 3
LoginGraceTime 20
'''
    ssh+=('Subsystem sftp internal-sftp\nChrootDirectory /srv/bridge\nForceCommand internal-sftp -d /inbox -u 0027\n' if cfg.role=='client' else 'ForceCommand /usr/local/libexec/bridge/receive-shot.py\n')
    conf='/etc/bridge/sshd-'+('inbox' if cfg.role=='client' else 'shot')+'.conf';put(conf,ssh)
    name='bridge-inbox' if cfg.role=='client' else 'bridge-shot'
    put('/etc/systemd/system/'+name+'.service','''[Unit]
Description=Waybridge restricted SSH endpoint
After=tailscaled.service network-online.target bridge-filter.service
Requires=bridge-filter.service
Wants=tailscaled.service
[Service]
ExecStartPre=/usr/bin/sshd -t -f '''+conf+'\nExecStart=/usr/bin/sshd -D -e -f '+conf+'\nRestart=on-failure\nRestartSec=2\nTimeoutStopSec=3\n[Install]\nWantedBy=multi-user.target\n')
    put('/etc/bridge/bridge-filter.nft',f'''destroy table inet bridge_guard
table inet bridge_guard {{
 chain input {{
  type filter hook input priority -10; policy accept;
  tcp dport {port} iifname != "tailscale0" drop
  tcp dport {port} ip saddr != {cfg.peer_ip} drop
 }}
}}''')
    put('/etc/systemd/system/bridge-filter.service','''[Unit]
Description=Waybridge peer firewall restriction
Before='''+name+'''.service
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/nft -f /etc/bridge/bridge-filter.nft
[Install]
WantedBy=multi-user.target
''')
    text+='nft -c -f /etc/bridge/bridge-filter.nft\nsshd -t -f '+q(conf)+'\nsystemctl daemon-reload\nsystemctl enable bridge-filter.service\nsystemctl restart bridge-filter.service\n'
    if cfg.role=='helper':text+='systemctl disable bridge-shot.service\necho \"Use waybridge start in the graphical session\"\n'
    else:text+='systemctl disable bridge-inbox.service\necho "Use waybridge start in the graphical session"\n'
    atomic(output,text.encode());output.chmod(0o700);print(output)


def link(cfg,hostkey):
    """Pin an authenticated peer host key; never trust an unauthenticated scan."""
    subprocess.run(['ssh-keygen','-l','-f',str(hostkey)],check=True,capture_output=True)
    values=[line.split() for line in hostkey.read_text().splitlines() if line.strip()]
    if len(values)!=1 or len(values[0])<2 or values[0][0]!='ssh-ed25519':raise ValueError('one Ed25519 host public key required')
    home=Path.home();ssh=home/'.ssh';ssh.mkdir(mode=0o700,exist_ok=True)
    port=2223 if cfg.role=='client' else 2222
    alias='bridge-shot' if cfg.role=='client' else 'bridge-inbox'
    known=ssh/'waybridge-known-hosts'
    atomic(known,(f'[{cfg.peer_ip}]:{port} '+' '.join(values[0][:2])+'\n').encode())
    fragment=ssh/'bridge.conf'
    backup=ssh/('bridge.conf.backup-'+time.strftime('%Y%m%d-%H%M%S'))
    if fragment.exists():shutil.copy2(fragment,backup)
    user=cfg.helper_user if cfg.role=='client' else 'bridge'
    text=f'Host {alias}\n    HostName {cfg.peer_ip}\n    Port {port}\n    User {user}\n    IdentityFile {ssh/alias}\n    IdentitiesOnly yes\n    BatchMode yes\n    StrictHostKeyChecking yes\n    UserKnownHostsFile {known}\n    ConnectTimeout 8\n    ServerAliveInterval 5\n    ServerAliveCountMax 2\n    RequestTTY no\n'
    atomic(fragment,text.encode())
    config=ssh/'config';old=config.read_text() if config.exists() else ''
    include='Include ~/.ssh/bridge.conf'
    if include not in old:atomic(config,(include+'\n'+old).encode())
    print('Pinned peer host key and configured:',alias)
