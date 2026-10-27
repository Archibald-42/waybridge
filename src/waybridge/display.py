"""Real battery capacity with an explicit transport readiness tint."""
import json
from pathlib import Path
import socket
import subprocess
import time
from .runtime import signals

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
            if not cfg.stopped.exists() and active(['systemctl'],['bridge-inbox.service','bridge-filter.service']) and active(['systemctl','--user'],['bridge-shot-queue.service','bridge-files.service']):
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
