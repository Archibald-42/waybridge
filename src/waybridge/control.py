"""Scoped lifecycle for screenshot and file transport only."""
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from .runtime import rpc

USER_UNITS=['bridge-shot-queue.service','bridge-files.service']
ROOT_UNITS=['bridge-inbox.service']

def run(cmd,timeout=12,check=True):
    result=subprocess.run(cmd,timeout=timeout,check=False,capture_output=True,text=True)
    if check and result.returncode:
        detail=(result.stderr or result.stdout).strip()[-600:]
        raise RuntimeError('Команда не выполнена: '+' '.join(cmd[:4])+(': '+detail if detail else ''))
    return result

def preflight(cfg):
    commands=['systemctl','busctl','tailscale','ssh','inotifywait']
    commands+=['grim','hyprctl'] if cfg.role=='client' else ['sftp','imv-wayland','imv-msg']
    missing=[name for name in commands if not shutil.which(name)]
    if missing:raise RuntimeError('Не установлены: '+', '.join(missing)+'. Запустите waybridge setup.')
    runtime=cfg.runtime
    if not runtime.is_dir() or runtime.stat().st_uid!=os.getuid():raise RuntimeError('Недоступна пользовательская графическая сессия (XDG_RUNTIME_DIR).')
    values=run(['systemctl','--user','show-environment']).stdout
    for line in values.splitlines():
        key,_,value=line.partition('=')
        if key in {'WAYLAND_DISPLAY','HYPRLAND_INSTANCE_SIGNATURE','XDG_CURRENT_DESKTOP'} and key not in os.environ:os.environ[key]=value
    display=os.environ.get('WAYLAND_DISPLAY')
    if not display or not (runtime/display).exists():raise RuntimeError('Wayland-сессия недоступна. Запустите waybridge start из терминала рабочего стола.')
    addresses=run(['tailscale','ip','-4']).stdout.splitlines()
    if cfg.own_ip not in addresses:raise RuntimeError('Tailscale не готов или изменился IP этого ПК. Проверьте tailscale status и waybridge setup.')
    folders=[cfg.state,cfg.projects] if cfg.role=='client' else [cfg.state,cfg.shots]
    for folder in folders:
        try:
            folder.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix='.waybridge-check-',dir=folder):pass
        except OSError as error:raise RuntimeError('Нет доступа для записи: '+str(folder)+'. Проверьте владельца и права.') from error
    if cfg.role=='client' and not os.access(cfg.inbox,os.R_OK|os.X_OK):raise RuntimeError('Нет доступа к входящей папке: '+str(cfg.inbox)+'. Повторите waybridge setup.')

def root_unit(action,unit):
    run(['busctl','--allow-interactive-authorization=no','call','org.freedesktop.systemd1',
         '/org/freedesktop/systemd1','org.freedesktop.systemd1.Manager',
         'StartUnit' if action=='start' else 'StopUnit','ss',unit,'replace'])
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        value=run(['systemctl','is-active',unit],check=False).stdout.strip()
        if action=='start' and value=='active':return
        if action=='stop' and value in {'inactive','failed'}:return
        if action=='start' and value=='failed':raise RuntimeError(unit+' не запустился. Подробности: journalctl -u '+unit+' -n 20')
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
        try:run(['systemctl','--user','kill','--signal=SIGKILL',*user_units],check=False)
        except (OSError,RuntimeError,subprocess.SubprocessError) as error:errors.append(str(error))
        errors.append('user units were force-terminated')
    except (OSError,RuntimeError,subprocess.SubprocessError) as error:errors.append(str(error))
    for unit in root_units:
        try:root_unit('stop',unit)
        except Exception as e:errors.append(str(e))
    if errors:raise RuntimeError('; '.join(errors))

def start(cfg):
    # Read-only checks must not turn a temporary missing desktop/network into a
    # persistent user stop request or discard an already working RAM queue.
    preflight(cfg)
    if run(['systemctl','is-active','bridge-filter.service'],check=False).stdout.strip()!='active':
        raise RuntimeError('bridge-filter.service is not active; refusing to open transport')
    cfg.stopped.touch()
    user_units,root_units=units(cfg)
    try:
        for unit in reversed(root_units):root_unit('start',unit)
        run(['systemctl','--user','reset-failed',*user_units],check=False)
        run(['systemctl','--user','start',*user_units])
        for name in user_units:
            if run(['systemctl','--user','is-active',name],check=False).stdout.strip()!='active':raise RuntimeError(name+' не готов; проверьте journalctl --user -u '+name)
        if cfg.role=='client':rpc(cfg.runtime/'bridge-shot-queue.sock','status')
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
    if action=='status':return status(cfg)
    with (cfg.state/'control.lock').open('w') as lock:
        deadline=time.monotonic()+5
        while True:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
            except BlockingIOError:
                if time.monotonic()>=deadline:raise RuntimeError('Другая операция ещё выполняется. Повторите команду через несколько секунд.')
                time.sleep(.05)
        if action=='start':start(cfg)
        elif action=='stop':stop(cfg)
        elif action=='restart':stop(cfg);start(cfg)
        else:raise ValueError('invalid control action')
    return {'ok':True,'action':action}
