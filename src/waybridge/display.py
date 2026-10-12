"""Waybar-only display state; never adjusts system time or battery capacity."""
import datetime
import json
import os
from pathlib import Path
import queue
import re
import socket
import subprocess
import threading
import time
from .runtime import atomic,signals

def clock_control(cfg,action):
    hidden=cfg.state/'clock-hidden';cfg.state.mkdir(parents=True,exist_ok=True)
    if action=='reset':atomic(cfg.inbox/'clock.txt',b'');hidden.unlink(missing_ok=True)
    elif action=='toggle':hidden.unlink() if hidden.exists() else hidden.touch()
    else:raise ValueError('reset or toggle required')

def clock(cfg):
    signals();cfg.state.mkdir(parents=True,exist_ok=True);events=queue.Queue()
    child=subprocess.Popen(['inotifywait','-m','-e','moved_to,close_write,delete','--format','%f',str(cfg.inbox),str(cfg.state)],
                           stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env={**os.environ,'LC_ALL':'C'})
    for line in child.stderr:
        if 'Watches established.' in line:break
    else:raise RuntimeError('clock watch failed')
    def reader():
        for line in child.stdout:
            if line.strip() in {'clock.txt','clock-hidden','stopped'}:events.put(True)
        events.put('stop')
    threading.Thread(target=reader,daemon=True).start();previous=None
    try:
        while True:
            now=datetime.datetime.now()
            try:
                with (cfg.inbox/'clock.txt').open() as f:answer=f.read(64).strip()
            except OSError:answer=''
            text=answer if not cfg.stopped.exists() and not (cfg.state/'clock-hidden').exists() and re.fullmatch('[0-9]{2}:[0-9]{2}',answer) else now.strftime('%H:%M')
            data=json.dumps({'text':text,'tooltip':now.strftime('%A, %d %B %Y')},ensure_ascii=False)
            if data!=previous:print(data,flush=True);previous=data
            try:
                if events.get(timeout=max(.01,60-now.second-now.microsecond/1000000))=='stop':raise RuntimeError('watch exited')
            except queue.Empty:pass
    finally:child.terminate();child.wait(timeout=2)

def notes(cfg):
    from .files import watch
    signals();child=watch(cfg.inbox)
    def emit():
        try:
            with (cfg.inbox/'answer.txt').open('rb') as f:text=f.read(16384).decode('utf-8',errors='replace')
        except OSError:text=''
        text=''.join(c for c in text if c>=' ' or c in '\n\t').replace('\t','    ')
        print(json.dumps({'text':text},ensure_ascii=False),flush=True)
    try:
        emit()
        for line in child.stdout:
            if line.strip()=='answer.txt':emit()
        raise RuntimeError('note watch exited')
    finally:child.terminate();child.wait(timeout=2)

def battery(cfg,once=False):
    signals();previous=None;last_probe=0.0;up=False
    def active(prefix,units):
        r=subprocess.run(prefix+['is-active',*units],capture_output=True,text=True,timeout=1)
        return r.stdout.splitlines()==['active']*len(units)
    while True:
        try:
            paths=list(Path('/sys/class/power_supply').glob('BAT*'))
            if not paths:raise OSError('battery unavailable')
            capacity=max(0,min(100,int((paths[0]/'capacity').read_text())))
            status=(paths[0]/'status').read_text().strip();online=False
            if not cfg.stopped.exists() and active(['systemctl'],['bridge-inbox.service','ydotool-bridge.service']) and active(['systemctl','--user'],['bridge-key-code.service','bridge-shot-queue.service','bridge-files.service']):
                value=json.loads(subprocess.check_output(['tailscale','status','--json'],timeout=1))
                online=value.get('Self',{}).get('Online',False) and any(p.get('Online') and cfg.peer_ip in p.get('TailscaleIPs',[]) for p in (value.get('Peer') or {}).values())
            if not online:up=False;last_probe=0
            elif time.monotonic()-last_probe>=15:
                last_probe=time.monotonic()
                try:
                    with socket.create_connection((cfg.peer_ip,2223),timeout=.5) as s:s.settimeout(.5);up=s.recv(256).startswith(b'SSH-2.0-')
                except OSError:up=False
            color='#ccd9ec' if up else '#e5cdd1';prefix='Заряд' if status=='Charging' else 'АКБ'
            data={'text':f'{prefix} <span foreground="{color}">{capacity}%</span>','tooltip':f'{capacity}% · {status}','class':'connected' if up else 'disconnected'}
        except (OSError,subprocess.SubprocessError,ValueError):data={'text':'АКБ —','class':'disconnected'}
        output=json.dumps(data,ensure_ascii=False)
        if output!=previous:print(output,flush=True);previous=output
        if once:return
        time.sleep(3)
