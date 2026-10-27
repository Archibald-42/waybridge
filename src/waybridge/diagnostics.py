"""Readable readiness checks; authenticated health requests never capture a screen."""
import json
import os
from pathlib import Path
import socket
import subprocess
from .control import units

def helper_health(cfg):
    env={**os.environ,'XDG_RUNTIME_DIR':f'/run/user/{os.getuid()}'}
    r=subprocess.run(['systemctl','--user','is-active','bridge-shot-view.service'],capture_output=True,text=True,timeout=2,env=env)
    try:viewer=json.loads((cfg.state/'gallery-status.json').read_text())
    except (OSError,ValueError):viewer=None
    return {'ok':True,'protocol':'WB1','gallery_service':r.stdout.strip()=='active','viewer':viewer}

def check(cfg):
    failed=False
    def result(label,ok,detail=''):
        nonlocal failed
        failed|=not ok
        print(('✓ ' if ok else '✗ ')+label+(': '+detail if detail else ''))
    print(f'Waybridge · {cfg.role} · {cfg.own_ip} → {cfg.peer_ip}')
    try:
        data=json.loads(subprocess.check_output(['tailscale','status','--json'],text=True,timeout=3))
        online=any(p.get('Online') and cfg.peer_ip in p.get('TailscaleIPs',[]) for p in (data.get('Peer') or {}).values())
        result('Второй ПК в Tailscale',online,'online' if online else 'offline / неизвестен')
    except (OSError,ValueError,subprocess.SubprocessError):result('Tailscale',False,'запустите tailscaled и авторизуйте устройство')
    user_units,root_units=units(cfg)
    for prefix,items in [(['systemctl'],root_units+['bridge-filter.service']),(['systemctl','--user'],user_units)]:
        for name in items:
            r=subprocess.run(prefix+['is-active',name],capture_output=True,text=True,timeout=3)
            result(name,r.stdout.strip()=='active',r.stdout.strip())
    alias='bridge-shot' if cfg.role=='client' else 'bridge-inbox'
    try:
        if cfg.role=='client':
            r=subprocess.run(['ssh','-T',alias],input=b'WBH1\n',capture_output=True,timeout=12)
            data=json.loads(r.stdout)
            result('SSH: ключ и pin проверены',r.returncode==0 and data.get('ok') is True)
            result('Галерея второго ПК',data.get('gallery_service') is True,'готова принимать; окно может быть закрыто')
        else:
            r=subprocess.run(['sftp','-q','-b','-',alias],input='ls /inbox\n',text=True,capture_output=True,timeout=12)
            result('SFTP: доступ к inbox клиента',r.returncode==0)
    except (OSError,ValueError,subprocess.SubprocessError):result('SSH/SFTP',False,'проверьте профиль peer, питание ПК и сеть; затем повторите setup')
    if failed:print('Исправление настроек / смена ПК: waybridge setup')
    else:print('Передача снимков и файлов готова.')
    return int(failed)
