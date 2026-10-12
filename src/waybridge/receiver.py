"""Restricted SSH command; validates, deduplicates and durably publishes PNG."""
import fcntl
import hashlib
import json
import os
import signal
import sys
import uuid
from .protocol import parse
from .runtime import atomic

def receive(cfg,stream=None):
    os.umask(0o077);signal.alarm(25)
    try:
        return _receive(cfg,stream or sys.stdin.buffer)
    finally:signal.alarm(0)

def _receive(cfg,stream):
    header,data=parse(stream)
    if header is None:
        header={'id':uuid.uuid4().hex,'sha256':hashlib.sha256(data).hexdigest(),'size':len(data)}
        legacy=True
    else:legacy=False
    cfg.shots.mkdir(parents=True,exist_ok=True,mode=0o700)
    target=cfg.shots/(header['id']+'.png')
    with (cfg.shots/'.receive.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest()!=header['sha256']:
                raise ValueError('job id reused with different content')
        else:atomic(target,data)
    # ACK только после fsync файла И каталога, с тем же ID/хешем.
    print('stored '+target.name if legacy else json.dumps({'ok':True,**header}),flush=True)
    signal.alarm(0)
    paths=[]
    for path in cfg.shots.glob('*.png'):
        try:paths.append((path.stat().st_mtime,path))
        except FileNotFoundError:continue
    for _,old in sorted(paths)[:-50]:old.unlink(missing_ok=True)
