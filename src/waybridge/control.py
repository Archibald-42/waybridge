"""Scoped systemd control, bounded deadlines, no keyboard rearming on recovery."""
import fcntl
import json
import subprocess
import time
from .runtime import rpc

USER_UNITS=['bridge-key-code.service','bridge-shot-queue.service','bridge-files.service','bridge-note.service']
ROOT_UNITS=['bridge-inbox.service','ydotool-bridge.service']

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

def stop(cfg):
    from .display import clock_control
    cfg.stopped.touch();errors=[]
    try:rpc(cfg.runtime/'bridge-key-code.sock','stop')
    except Exception:pass
    try:
        r=run(['systemctl','--user','stop',*USER_UNITS],check=False)
        if r.returncode:errors.append('user units could not stop')
    except subprocess.TimeoutExpired:
        run(['systemctl','--user','kill','--signal=SIGKILL',*USER_UNITS],check=False)
        errors.append('user units were force-terminated')
    for unit in ROOT_UNITS:
        try:root_unit('stop',unit)
        except Exception as e:errors.append(str(e))
    clock_control(cfg,'reset')
    if errors:raise RuntimeError('; '.join(errors))

def start(cfg):
    from .display import clock_control
    cfg.stopped.touch()
    try:
        clock_control(cfg,'reset')
        if run(['systemctl','is-active','bridge-filter.service'],check=False).stdout.strip()!='active':
            raise RuntimeError('bridge-filter.service is not active; refusing to open transport')
        for unit in reversed(ROOT_UNITS):root_unit('start',unit)
        run(['systemctl','--user','reset-failed',*USER_UNITS],check=False)
        run(['systemctl','--user','start',*USER_UNITS])
        rpc(cfg.runtime/'bridge-key-code.sock','stop')
        cfg.stopped.unlink(missing_ok=True)
    except Exception:
        try:stop(cfg)
        except Exception:pass
        raise

def status(cfg):
    data={'stopped':cfg.stopped.exists()}
    for name,prefix,units in [('client',['systemctl','--user'],USER_UNITS),('transport',['systemctl'],ROOT_UNITS)]:
        data[name]=dict(zip(units,run(prefix+['is-active',*units],check=False).stdout.splitlines()))
    for name,endpoint in [('input','bridge-key-code.sock'),('queue','bridge-shot-queue.sock')]:
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
        elif action=='reset':
            from .display import clock_control
            clock_control(cfg,'reset')
        else:raise ValueError('invalid control action')
    return {'ok':True,'action':action}
