"""Atomic SFTP push and local inotify projection preserving original names."""
import fcntl
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time
import uuid
from .runtime import atomic,signals

NAME=re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}')
SUFFIXES={'.py','.cpp','.c','.h','.hpp','.rs','.js','.ts','.java','.go','.sh','.txt','.json'}
LIMIT=32*1024*1024

def push(cfg,source,name=None):
    source=Path(source);name=name or source.name
    if not NAME.fullmatch(name):raise ValueError('ASCII filename required')
    with source.open('rb') as f:data=f.read(LIMIT+1)
    if len(data)>LIMIT:raise ValueError('file exceeds 32 MiB')
    cfg.state.mkdir(parents=True,exist_ok=True)
    with (cfg.state/'push.lock').open('w') as lock,tempfile.TemporaryDirectory(prefix='waybridge-push-') as td:
        fcntl.flock(lock,fcntl.LOCK_EX)
        local=Path(td)/'payload';local.write_bytes(data);identifier=uuid.uuid4().hex
        batch=f'put -f "{local}" /inbox/.partial-{identifier}\nrename /inbox/.partial-{identifier} /inbox/{name}\n'
        for attempt in range(4):
            try:
                r=subprocess.run(['sftp','-q','-b','-','bridge-inbox'],input=batch,text=True,timeout=60,capture_output=True)
                if r.returncode==0:return
            except subprocess.TimeoutExpired:pass
            if attempt<3:time.sleep(2**attempt)
    raise RuntimeError('SFTP delivery failed; local source preserved')

def watch(folder):
    child=subprocess.Popen(['inotifywait','-m','-e','moved_to,close_write,delete','--format','%f',str(folder)],
                           stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                           env={**os.environ,'LC_ALL':'C'})
    for line in child.stderr:
        if 'Watches established.' in line:return child
    child.wait();raise RuntimeError('inotify watch failed')

def publish(cfg,name):
    if not NAME.fullmatch(name):return False
    source=cfg.inbox/name
    if source.suffix not in SUFFIXES:return False
    try:
        fd=os.open(source,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):return False
            data=f.read(LIMIT+1)
    except OSError:return False
    if len(data)>LIMIT:return False
    target=cfg.projects/name
    if target.is_file() and not target.is_symlink():
        with target.open('rb') as f:old=f.read(LIMIT+1)
        if len(old)>LIMIT:raise ValueError('existing project file exceeds backup limit; preserving original')
        if old!=data:
            digest=hashlib.sha256(old).hexdigest()[:16]
            atomic(cfg.state/'versions'/(name+'.'+digest),old)
            atomic(target,data)
    else:atomic(target,data)
    return True

def serve(cfg):
    signals();cfg.projects.mkdir(parents=True,exist_ok=True);cfg.state.mkdir(parents=True,exist_ok=True)
    child=watch(cfg.inbox)
    try:
        paths=[]
        for path in cfg.inbox.iterdir():
            try:paths.append((path.stat().st_mtime,path.name))
            except FileNotFoundError:continue
        for _,name in sorted(paths):publish(cfg,name)
        for line in child.stdout:publish(cfg,line.rstrip('\n'))
        raise RuntimeError('inotify process exited')
    finally:child.terminate();child.wait(timeout=2)

