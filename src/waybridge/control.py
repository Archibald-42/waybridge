"""Scoped lifecycle for screenshot and file transport only."""
import fcntl
import json
import subprocess
import time
from .runtime import rpc

USER_UNITS=['bridge-shot-queue.service','bridge-files.service']
ROOT_UNITS=['bridge-inbox.service']

def run(cmd,timeout=12,check=True):
    return subprocess.run(cmd,timeout=timeout,check=check,capture_output=True,text=True)

def root_unit(action,unit):
    run(['busctl','--allow-interactive-authorization=no','call','org.freedesktop.systemd1',
         '/org/freedesktop/systemd1','org.freedesktop.systemd1.Manager',
         'StartUnit' if action=='start' else 'StopUnit','ss',unit,'replace'])
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        value=run(['systemctl','is-active',unit],check=False).stdout.strip()
        if action=='start' and value=='active':return
        if action=='stop' and value in {'inactive','failed'}:return
        time.sleep(.05)
    raise RuntimeError(f'{action} timed out: {unit}')

def units(cfg):
    return (USER_UNITS,ROOT_UNITS) if cfg.role=='client' else (['bridge-shot-view.service'],['bridge-shot.service'])

def stop(cfg):
    cfg.stopped.touch();errors=[]
    user_units,root_units=units(cfg)
    try:
        r=run(['systemctl','--user','stop',*user_units],check=False)
        if r.returncode:errors.append('user units could not stop')
    except subprocess.TimeoutExpired:
        run(['systemctl','--user','kill','--signal=SIGKILL',*user_units],check=False)
        errors.append('user units were force-terminated')
    for unit in root_units:
        try:root_unit('stop',unit)
        except Exception as e:errors.append(str(e))
    if errors:raise RuntimeError('; '.join(errors))

def start(cfg):
    cfg.stopped.touch()
    user_units,root_units=units(cfg)
    try:
        if run(['systemctl','is-active','bridge-filter.service'],check=False).stdout.strip()!='active':
            raise RuntimeError('bridge-filter.service is not active; refusing to open transport')
        for unit in reversed(root_units):root_unit('start',unit)
        run(['systemctl','--user','reset-failed',*user_units],check=False)
        run(['systemctl','--user','start',*user_units])
        cfg.stopped.unlink(missing_ok=True)
    except Exception:
        try:stop(cfg)
        except Exception:pass
        raise

def status(cfg):
    user_units,root_units=units(cfg)
    data={'role':cfg.role,'stopped':cfg.stopped.exists()}
    for name,prefix,unit_names in [(cfg.role,['systemctl','--user'],user_units),('transport',['systemctl'],root_units)]:
        data[name]=dict(zip(unit_names,run(prefix+['is-active',*unit_names],check=False).stdout.splitlines()))
    for name,endpoint in ([('queue','bridge-shot-queue.sock')] if cfg.role=='client' else []):
        try:data[name]=rpc(cfg.runtime/endpoint,'status')
        except Exception:data[name]={'ok':False}
    return data

def execute(cfg,action):
    cfg.state.mkdir(parents=True,exist_ok=True)
    with (cfg.state/'control.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if action=='start':start(cfg)
        elif action=='stop':stop(cfg)
        elif action=='status':return status(cfg)
        else:raise ValueError('invalid control action')
    return {'ok':True,'action':action}
