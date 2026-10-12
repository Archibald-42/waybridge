"""Supervised imv gallery; stable hardlinks and safe removal around imv 5.0.1."""
import json
import os
from pathlib import Path
import re
import selectors
import stat
import subprocess
import tempfile
import time
from .files import watch
from .runtime import atomic,signals

IMAGE=re.compile(r'[a-f0-9]{32}\.png')

def images(folder):
    found=[]
    for path in folder.iterdir():
        if not IMAGE.fullmatch(path.name):continue
        try:
            info=path.lstat()
            if stat.S_ISREG(info.st_mode):found.append((info.st_mtime_ns,path.name,path))
        except FileNotFoundError:continue
    return [p for _,_,p in sorted(found)][-50:]

class Viewer:
    """An immutable anchor keeps index 0 valid while earlier frames are removed.

    imv 5.0.1 does not decrement its selected index when a preceding entry is
    closed. Select the anchor BEFORE closing history, then select the new end.
    Hardlinks stop receiver retention from invalidating imv's source paths.
    """
    def __init__(self,cfg):
        self.cfg=cfg;self.process=None;self.opened=[];self.cache=None
        self.latest=None;self.ready=False;self.attempts=0;self.retry_at=0
        self.started_at=0.0;self.dismissed=False;self.reason='waiting for image'
    def report(self):
        atomic(self.cfg.state/'gallery-status.json',json.dumps({
            'pid':self.process.pid if self.process and self.process.poll() is None else None,
            'latest':self.latest,'ready':self.ready,'attempts':self.attempts,
            'reason':self.reason},ensure_ascii=False).encode())
    def message(self,text):
        subprocess.run(['imv-msg',str(self.process.pid),text],check=True,timeout=2,
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    def close(self):
        self.ready=False
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=2)
        self.process=None;self.opened=[]
        if self.cache:self.cache.cleanup();self.cache=None
    def link(self,source):
        destination=Path(self.cache.name)/source.name
        if not destination.exists():os.link(source,destination,follow_symlinks=False)
        return destination
    def start(self,paths):
        self.close()
        if not paths:return
        self.cache=tempfile.TemporaryDirectory(prefix='gallery-',dir=self.cfg.state)
        available=[]
        for source in paths:
            try:self.link(source);available.append(source.name)
            except FileNotFoundError:continue
        if not available:self.close();return
        anchor=Path(self.cache.name)/'anchor.png'
        os.link(Path(self.cache.name)/available[-1],anchor)
        self.opened=['anchor.png',*available]
        # Anchor is an extra first entry; all real frames retain chronological order.
        args=['imv-wayland','-i','waybridge-gallery','-w','Waybridge — снимки',
              '-c','bind x quit','-n',str(len(self.opened)),
              *[str(Path(self.cache.name)/name) for name in self.opened]]
        self.process=subprocess.Popen(args,stdin=subprocess.DEVNULL)
        deadline=time.monotonic()+3
        endpoint=self.cfg.runtime/f'imv-{self.process.pid}.sock'
        while not endpoint.exists() and self.process.poll() is None and time.monotonic()<deadline:time.sleep(.02)
        if self.process.poll() is not None or not endpoint.exists():raise RuntimeError('viewer startup failed')
        self.ready=True;self.started_at=time.monotonic();self.reason='running';self.report()
    def reconcile(self,paths):
        names={p.name for p in paths};added=False
        for path in paths:
            if path.name in self.opened:continue
            try:target=self.link(path)
            except FileNotFoundError:continue
            quoted='"'+str(target).replace('\\','\\\\').replace('"','\\"')+'"'
            self.message('open '+quoted);self.opened.append(path.name);added=True
        removed=[i for i,name in enumerate(self.opened) if i and name not in names]
        if removed:
            # Do not let imv retain a past-the-end selection during close N.
            self.message('goto 1')
            for index in reversed(removed):
                name=self.opened[index];self.message('close '+str(index+1))
                self.opened.pop(index);(Path(self.cache.name)/name).unlink(missing_ok=True)
        if added or removed:self.message('goto -1')
        self.reason='running';self.report()
    def refresh(self,new_event=False):
        paths=images(self.cfg.shots)
        if not paths:return
        newest=paths[-1].name
        new=newest!=self.latest
        if new:self.latest=newest;self.dismissed=False;self.attempts=0;self.retry_at=0
        if self.process and self.process.poll() is not None:
            rc=self.process.returncode;self.close()
            if rc==0 and not new:self.dismissed=True;self.reason='closed by user';self.report();return
            self.reason=f'viewer exited ({rc}); retrying';self.retry_at=time.monotonic()+.3
        if self.process and self.process.poll() is None and time.monotonic()-self.started_at>5:self.attempts=0
        if self.dismissed or self.attempts>=3 or time.monotonic()<self.retry_at:return
        try:
            if not self.process:self.attempts+=1;self.start(paths)
            elif new_event:self.reconcile(paths)
        except (OSError,RuntimeError,subprocess.SubprocessError) as error:
            self.close();self.reason=type(error).__name__+': '+str(error)
            self.retry_at=time.monotonic()+.5;self.report()
            print('gallery recovery:',self.reason,flush=True)
            if self.attempts>=3:print('gallery paused after 3 attempts; inspect gallery-status.json',flush=True)

def serve(cfg):
    signals();cfg.shots.mkdir(parents=True,exist_ok=True,mode=0o700)
    import shutil
    for leftover in cfg.state.glob('gallery-*'):
        if leftover.is_dir() and not leftover.is_symlink():shutil.rmtree(leftover)
    child=watch(cfg.shots);viewer=Viewer(cfg);selector=selectors.DefaultSelector()
    os.set_blocking(child.stdout.fileno(),False);selector.register(child.stdout,selectors.EVENT_READ)
    pending=b''
    try:
        viewer.refresh(True)
        while True:
            changed=False
            for key,_ in selector.select(.2):
                block=os.read(key.fileobj.fileno(),65536)
                if not block:raise RuntimeError('gallery watch exited')
                pending+=block
                while b'\n' in pending:
                    name,pending=pending.split(b'\n',1)
                    if IMAGE.fullmatch(name.decode('utf-8',errors='replace')):changed=True
            viewer.refresh(changed)
    finally:
        viewer.close();selector.close();child.terminate();child.wait(timeout=2)
