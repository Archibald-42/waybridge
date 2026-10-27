"""Portable public-only pairing profiles; never export private keys or runtime data."""
import base64
import hashlib
import ipaddress
import json
from pathlib import Path
import pwd
import os
import re
import socket
import struct
import subprocess
from .runtime import atomic

FORMAT='waybridge-pair/1'
ACCOUNT=re.compile(r'[a-z_][a-z0-9_-]{0,31}')

def public_key(value):
    if not isinstance(value,str):raise ValueError('public key must be text')
    fields=value.split()
    if len(fields)<2 or fields[0]!='ssh-ed25519':raise ValueError('Ed25519 PUBLIC key required')
    try:raw=base64.b64decode(fields[1],validate=True)
    except ValueError:raise ValueError('invalid public key encoding') from None
    # SSH wire format: string algorithm, string 32-byte key.
    expected=struct.pack('>I',11)+b'ssh-ed25519'+struct.pack('>I',32)
    if len(raw)!=len(expected)+32 or not raw.startswith(expected):raise ValueError('invalid Ed25519 public key structure')
    return fields[0]+' '+fields[1]

def validate(data):
    if not isinstance(data,dict) or data.get('format')!=FORMAT:raise ValueError('not a Waybridge pairing profile')
    if set(data)!={'format','role','user','ip','auth_key','host_key','hostname'}:raise ValueError('unexpected profile fields')
    data={**data,'role':'server' if data.get('role')=='helper' else data.get('role')}
    if data['role'] not in {'client','server'}:raise ValueError('invalid profile role')
    if not isinstance(data['user'],str) or not ACCOUNT.fullmatch(data['user']):raise ValueError('invalid Linux account')
    if not isinstance(data['ip'],str) or ipaddress.IPv4Address(data['ip']) not in ipaddress.IPv4Network('100.64.0.0/10'):raise ValueError('Tailscale IPv4 required')
    if not isinstance(data['hostname'],str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',data['hostname']):raise ValueError('invalid hostname')
    return {**data,'auth_key':public_key(data['auth_key']),'host_key':public_key(data['host_key'])}

def read(path):
    with Path(path).expanduser().open('rb') as f:data=f.read(16385)
    if len(data)>16384:raise ValueError('pairing profile too large')
    return validate(json.loads(data))

def fingerprint(profile):
    canonical=json.dumps(validate(profile),sort_keys=True,separators=(',',':')).encode()
    code=hashlib.sha256(canonical).hexdigest()[:12].upper()
    return '-'.join(code[i:i+4] for i in range(0,12,4))

def local(role):
    if role not in {'client','server'}:raise ValueError('choose client or server')
    user=pwd.getpwuid(os.getuid()).pw_name
    key=Path.home()/'.ssh'/('bridge-shot' if role=='client' else 'bridge-inbox')
    key.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if not key.exists():subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)],check=True)
    own=subprocess.check_output(['tailscale','ip','-4'],text=True,timeout=3).strip()
    host=Path('/etc/ssh/ssh_host_ed25519_key.pub')
    if not host.exists():raise RuntimeError('host public key missing; run setup to create it')
    return validate({'format':FORMAT,'role':role,'user':user,'ip':own,'hostname':socket.gethostname(),
                     'auth_key':Path(str(key)+'.pub').read_text(),'host_key':host.read_text()})

def export(role,output=None):
    profile=local(role)
    path=Path(output).expanduser() if output else Path.home()/'Downloads'/f'waybridge-{profile["hostname"]}-{role}.wbpair'
    atomic(path,(json.dumps(profile,ensure_ascii=False,indent=2)+'\n').encode())
    print('Публичный профиль:',path)
    print('Код сверки:',fingerprint(profile))
    return path,profile

def configuration(own,peer,previous=None):
    own=validate(own);peer=validate(peer)
    if own['role']==peer['role']:raise ValueError('pair must contain one client and one server')
    if own['ip']==peer['ip']:raise ValueError('choose the OTHER device profile')
    data=dict(previous or {})
    for key in ('keyboard','hold_ms','api_timeout','loop_limit','helper_user'):data.pop(key,None)
    data.update(role=own['role'],own_ip=own['ip'],peer_ip=peer['ip'],user=own['user'],
                server_user=peer['user'] if own['role']=='client' else own['user'])
    return data
