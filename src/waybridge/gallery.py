"""One Wayland image window with IPC navigation; no root required."""
import os
from pathlib import Path
import re
import subprocess
import time
from .files import watch
from .runtime import signals

def serve(cfg):
    signals();cfg.shots.mkdir(parents=True,exist_ok=True,mode=0o700)
    child=watch(cfg.shots);viewer=None;opened=[]
    def display(path=None):
        nonlocal viewer,opened
        if viewer is None or viewer.poll() is not None:
            paths=sorted(cfg.shots.glob('*.png'),key=lambda p:p.stat().st_mtime)
            if not paths:return
            viewer=subprocess.Popen(['imv-wayland','-n',str(paths[-1]),*[str(p) for p in paths]])
            opened=list(paths);sock=cfg.runtime/f'imv-{viewer.pid}.sock';deadline=time.monotonic()+3
            while not sock.exists() and viewer.poll() is None and time.monotonic()<deadline:time.sleep(.02)
        elif path and path.exists() and path not in opened:
            # IPC parser принимает пробелы в quoted paths; имена кадров всегда hex.
            quoted='"'+str(path).replace('\\','\\\\').replace('"','\\"')+'"'
            subprocess.run(['imv-msg',str(viewer.pid),'open '+quoted],check=True,timeout=2)
            opened.append(path)
            for index in range(len(opened)-1,-1,-1):
                if not opened[index].exists():
                    subprocess.run(['imv-msg',str(viewer.pid),'close '+str(index+1)],check=True,timeout=2)
                    opened.pop(index)
            subprocess.run(['imv-msg',str(viewer.pid),'goto -1'],check=True,timeout=2)
    try:
        display()
        for line in child.stdout:
            name=line.strip()
            if re.fullmatch(r'[a-f0-9]{32}\.png',name):
                path=cfg.shots/name
                if path.exists():display(path)
                elif viewer and viewer.poll() is None:
                    for index in range(len(opened)-1,-1,-1):
                        if not opened[index].exists():
                            subprocess.run(['imv-msg',str(viewer.pid),'close '+str(index+1)],check=True,timeout=2)
                            opened.pop(index)
        raise RuntimeError('gallery watch exited')
    finally:
        child.terminate();child.wait(timeout=2)
        if viewer and viewer.poll() is None:viewer.terminate()
