"""Configuration contains deployment data; source code contains none."""
from dataclasses import dataclass
import ipaddress
import os
from pathlib import Path
import re
import tomllib

@dataclass(frozen=True)
class Config:
    role: str
    peer_ip: str
    own_ip: str
    user: str
    helper_user: str
    inbox: Path
    projects: Path
    state: Path
    queue_count: int = 8
    queue_bytes: int = 67108864
    png_limit: int = 33554432
    @property
    def runtime(self):
        path = os.environ.get('XDG_RUNTIME_DIR')
        if not path: raise RuntimeError('XDG_RUNTIME_DIR is not set; enter a user session')
        return Path(path)
    @property
    def shots(self): return self.state / 'shots'
    @property
    def stopped(self): return self.state / 'stopped'

def default_path():
    return Path(os.environ.get('WAYBRIDGE_CONFIG', Path.home()/'.config/waybridge/config.toml'))

def load(path=None):
    with Path(path or default_path()).open('rb') as f: data=tomllib.load(f)
    home=Path.home()
    if data.get('role') not in {'client','helper'}: raise ValueError('role must be client or helper')
    for field in ('own_ip','peer_ip'):
        if not isinstance(data.get(field),str):raise ValueError('IP fields must be strings')
        ip=ipaddress.IPv4Address(data[field])
        if ip not in ipaddress.IPv4Network('100.64.0.0/10'): raise ValueError('Tailscale IPv4 required')
    for field in ('user','helper_user'):
        if not isinstance(data.get(field),str) or not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}',data[field]): raise ValueError('invalid account name')
    def path_value(key,default):
        raw=data.get(key,str(default))
        if not isinstance(raw,str):raise ValueError('path fields must be strings')
        value=Path(raw).expanduser()
        if not value.is_absolute() or '\n' in str(value): raise ValueError('absolute paths without newlines required')
        return value
    c=Config(data['role'],data['peer_ip'],data['own_ip'],data['user'],data['helper_user'],
             path_value('inbox','/srv/bridge/inbox'),path_value('projects',home/'Documents/projects'),
             path_value('state',home/'.cache/bridge'),
             **{k:data[k] for k in ('queue_count','queue_bytes','png_limit') if k in data})
    if any(type(getattr(c,k)) is not int for k in ('queue_count','queue_bytes','png_limit')):raise ValueError('integer limits required')
    if not (1<=c.queue_count<=16 and 1048576<=c.queue_bytes<=268435456 and 1048576<=c.png_limit<=33554432):
        raise ValueError('invalid RAM/queue limits')
    return c
