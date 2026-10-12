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

def bindings(config,hold=0):
    lines=['-- Waybridge: physical Numpad keycodes; NumLock-independent.']
    for code,action in [(79,'start'),(80,'shot'),(81,'kill'),(83,'input'),(84,'reset'),(85,'clock')]:
        down=command(config,'trigger '+action+' down')
        lines.append('hl.bind('+json.dumps(' + code:'+str(code))+', hl.dsp.exec_cmd('+json.dumps(down)+'))')
        if hold and action!='kill':
            up=command(config,'trigger '+action+' up')
            lines.append('hl.bind('+json.dumps(' + code:'+str(code))+', hl.dsp.exec_cmd('+json.dumps(up)+'), { release = true })')
    lines+=['hl.permission("/usr/bin/grim", "screencopy", "allow")',
            'hl.device({ name = "ydotoold-virtual-device", kb_layout = "us", kb_options = "" })',
            'hl.on("hyprland.start", function() hl.exec_cmd('+json.dumps(command(config,'session-start'))+') end)']
    return '\n'.join(lines)+'\n'

def user_install(cfg,config):
    home=Path.home();backup=home/'.local/state/waybridge/backups'/time.strftime('%Y%m%d-%H%M%S')
    def write(path,data,mode=0o644):
        path=Path(path)
        if path.exists():
            dest=backup/path.relative_to(home);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,dest)
        atomic(path,data.encode());path.chmod(mode)
    wrappers={'bridge':'control','key-code.py':'input','shot-send.sh':'shot request','bridge-clock.py':'clock','battery-link.py':'battery','note-stream.py':'notes','bridge-session-start.sh':'session-start','send-code':'send-code','send-answer':'send-answer','push-file.py':'send-code'}
    if cfg.role=='helper':wrappers={k:v for k,v in wrappers.items() if k in {'send-code','send-answer','push-file.py'}}
    else:wrappers={k:v for k,v in wrappers.items() if k not in {'send-code','send-answer','push-file.py'}}
    for name,args in wrappers.items():
        # Default worker command for backwards-compatible Waybar scripts.
        if name=='bridge-clock.py':
            write(home/'.local/bin'/name,'#!/bin/sh\nif [ \"$#\" -eq 0 ]; then set -- serve; fi\nexec '+command(config,'clock')+' \"$@\"\n',0o755)
            continue
        write(home/'.local/bin'/name,'#!/bin/sh\nexec '+command(config,args)+' "$@"\n',0o755)
    units=home/'.config/systemd/user'
    if cfg.role=='client':
        for name,args,wd in [('bridge-key-code','input serve',True),('bridge-shot-queue','shot serve',True),('bridge-files','files',False)]:
            text=unit(config,args,wd)
            if name=='bridge-key-code':text+='ExecStopPost=-'+command(config,'release')+'\n'
            write(units/(name+'.service'),text)
        for name,action in [('bridge-start','start'),('bridge-kill','stop')]:
            write(units/(name+'.service'),'[Unit]\nDescription=Waybridge '+action+'\n[Service]\nType=oneshot\nTimeoutStartSec=45\nExecStart='+command(config,'control '+action)+'\n')
        bridge=home/'.config/bridge';bridge.mkdir(parents=True,exist_ok=True)
        write(bridge/'hypr-client.lua',bindings(config,cfg.hold_ms))
        note={'name':'bridge-note','layer':'overlay','position':'top','exclusive':False,'passthrough':True,'modules-center':['custom/bridge-note'],'custom/bridge-note':{'exec':command(config,'notes'),'return-type':'json','restart-interval':2,'escape':True,'tooltip':False}}
        write(bridge/'note-waybar.jsonc',json.dumps(note,ensure_ascii=False,indent=2)+'\n')
        write(bridge/'note-waybar.css','window#waybar { background: rgba(20,22,26,0.85); color: #eee; font-size: 16px; }\n#custom-bridge-note { padding: 8px; }\n')
        write(units/'bridge-note.service','[Unit]\nDescription=Waybridge text panel\nPartOf=graphical-session.target\nStartLimitIntervalSec=60\nStartLimitBurst=3\n[Service]\nExecStart=/usr/bin/waybar -c '+str(bridge/'note-waybar.jsonc')+' -s '+str(bridge/'note-waybar.css')+'\nRestart=on-failure\nRestartSec=2\nTimeoutStopSec=3\n')
        # Standalone include, never rewrites an unrelated user's Waybar layout.
        write(bridge/'waybar-modules.json',json.dumps({'custom/bridge-clock':{'exec':command(config,'clock serve'),'return-type':'json','restart-interval':2,'escape':True},'custom/battery':{'exec':command(config,'battery'),'return-type':'json','restart-interval':3}},indent=2)+'\n')
    else:write(units/'bridge-shot-view.service',unit(config,'gallery'))
    subprocess.run(['systemctl','--user','daemon-reload'],check=True,timeout=5)
    print('Installed user files. Backup:',backup)
    print('Client module:',home/'.config/bridge/hypr-client.lua')
    print('No service was started; input remains OFF.')

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
    dependencies='openssh nftables python inotify-tools '+('ydotool acl grim' if cfg.role=='client' else 'imv')
    text+='pacman -S --needed --noconfirm '+dependencies+'\n'
    text+='backup=/var/lib/waybridge/backups/$(date +%Y%m%d-%H%M%S)\ninstall -d -m 700 \"$backup\"\nfor path in /etc/bridge /etc/systemd/system/bridge-inbox.service /etc/systemd/system/bridge-shot.service /etc/systemd/system/bridge-filter.service /etc/systemd/system/ydotool-bridge.service /etc/udev/rules.d/90-bridge-key-code.rules /etc/polkit-1/rules.d/49-bridge-units.rules /usr/local/libexec/bridge/receive-shot.py; do\n if [[ -e $path ]]; then cp -a --parents \"$path\" \"$backup\"; fi\ndone\n'
    text+='install -d -o root -g root -m 755 /etc/bridge /etc/bridge/keys /usr/local/libexec/bridge\nssh-keygen -A\n'
    def put(path,data,mode=644):
        nonlocal text
        text+='cat > '+q(path)+" <<'WAYBRIDGE_FILE'\n"+data+'\nWAYBRIDGE_FILE\nchmod '+str(mode)+' '+q(path)+'\nchown root:root '+q(path)+'\n'
    if cfg.role=='client':
        text+='''getent group bridge-files >/dev/null || groupadd bridge-files
getent group bridge-input >/dev/null || groupadd bridge-input
if ! id bridge >/dev/null 2>&1; then useradd -M -g bridge-files -d /inbox -s /usr/bin/nologin bridge; fi
[[ $(getent passwd bridge | cut -d: -f6) == /inbox ]] || exit 1
usermod -aG bridge-files,bridge-input "$target_user"
install -d -o root -g root -m 755 /srv/bridge
install -d -o bridge -g bridge-files -m 2770 /srv/bridge/inbox
setfacl -m "u:$target_uid:rwx,d:u:$target_uid:rwx,d:m:rwx" /srv/bridge/inbox
'''
        # This version uses UID and root GID: socket mode confines access to one UID.
        put('/etc/systemd/system/ydotool-bridge.service',f'''[Unit]
Description=Waybridge scoped virtual keyboard
[Service]
ExecStart=/usr/bin/ydotoold --socket-path=/run/bridge-input/ydotool.sock --socket-own={uid}:0 --socket-perm=0660
RuntimeDirectory=bridge-input
RuntimeDirectoryMode=0755
Restart=on-failure
RestartSec=2
TimeoutStopSec=3
''')
        keyboard_name=subprocess.check_output(['udevadm','info','--attribute-walk','--name',str(cfg.keyboard)],text=True,timeout=3)
        import re
        match=re.search(r'ATTRS\{name\}=="([^"\n]+)"',keyboard_name)
        if not match:raise ValueError('keyboard parent name not found')
        # Match sysfs parent name AND the exact selected event syspath, not all keyboards.
        syspath=subprocess.check_output(['udevadm','info','--query=path','--name',str(cfg.keyboard)],text=True).strip()
        parent=syspath.rsplit('/input',1)[0]
        rule=f'ACTION=="add|change", SUBSYSTEM=="input", KERNEL=="event*", ATTRS{{name}}=="{match[1]}", DEVPATH=="{parent}/input*/event*", RUN+="/usr/bin/setfacl -m u:{uid}:r /dev/%k"'
        put('/etc/udev/rules.d/90-bridge-key-code.rules',rule)
        text+='udevadm control --reload-rules\nsetfacl -m u:'+str(uid)+':r '+q(cfg.keyboard)+'\n'
        put('/etc/polkit-1/rules.d/49-bridge-units.rules','''polkit.addRule(function(action, subject) {
    if (action.id === "org.freedesktop.systemd1.manage-units" && subject.user === '''+json.dumps(cfg.user)+''') {
        var unit = action.lookup("unit"), verb = action.lookup("verb");
        if ((unit === "bridge-inbox.service" || unit === "ydotool-bridge.service") && (verb === "start" || verb === "stop")) return polkit.Result.YES;
    }
});''')
    else:
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
    text+='nft -c -f /etc/bridge/bridge-filter.nft\nsshd -t -f '+q(conf)+'\nsystemctl daemon-reload\nsystemctl enable --now bridge-filter.service\n'
    if cfg.role=='helper':text+='systemctl enable --now bridge-shot.service\n'
    else:text+='systemctl disable bridge-inbox.service ydotool-bridge.service\necho "Use waybridge control start in the graphical session; input stays OFF"\n'
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
