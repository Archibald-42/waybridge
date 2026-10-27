"""Explicit command interface; imports never start workers or intercept input."""
import argparse
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import time
from .config import load, default_path,role
from .runtime import atomic, rpc

def initialize(args):
    own=subprocess.check_output(['tailscale','ip','-4'],text=True,timeout=3).strip()
    user=pwd.getpwuid(os.getuid()).pw_name
    data={'role':args.role,'own_ip':own,'peer_ip':args.peer_ip,'user':user,
          'server_user':args.server_user or user}
    path=Path(args.config or default_path())
    if path.exists():raise RuntimeError('configuration already exists; edit it explicitly')
    atomic(path,('\n'.join(k+' = '+json.dumps(v) for k,v in data.items())+'\n').encode())
    try:load(path)
    except Exception:path.unlink();raise
    key=Path.home()/'.ssh'/('bridge-shot' if args.role=='client' else 'bridge-inbox')
    key.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if not key.exists():subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)],check=True)
    print(path)
    print('Share ONLY public key:',str(key)+'.pub')

def trigger(cfg,action,phase):
    if phase!='down':return
    if action in {'start','kill'}:
        subprocess.run(['systemctl','--user','start','--no-block',
                        'bridge-start.service' if action=='start' else 'bridge-kill.service'],check=True,timeout=2)
    elif action=='shot':print(json.dumps(rpc(cfg.runtime/'bridge-shot-queue.sock','shot')))

def doctor(cfg):
    import shutil
    commands=['tailscale','ssh','sftp','systemctl','inotifywait']
    commands+=['hyprctl','grim'] if cfg.role=='client' else ['imv-wayland','imv-msg']
    results={x:bool(shutil.which(x)) for x in commands}
    if cfg.role=='client':
        results['inbox-readable']=os.access(cfg.inbox,os.R_OK)
    results['runtime-directory']=bool(os.environ.get('XDG_RUNTIME_DIR'))
    print(json.dumps(results,ensure_ascii=False,indent=2))
    return 0 if all(results.values()) else 1

def main():
    from . import __version__
    p=argparse.ArgumentParser(prog='waybridge');p.add_argument('--config');p.add_argument('--version',action='version',version='%(prog)s '+__version__)
    sub=p.add_subparsers(dest='command',required=True)
    init=sub.add_parser('init');init.add_argument('--role',type=role,choices=['client','server'],required=True);init.add_argument('--peer-ip',required=True);init.add_argument('--server-user')
    sub.add_parser('doctor');sub.add_parser('install-user');sub.add_parser('check')
    uninstall=sub.add_parser('uninstall');uninstall.add_argument('--yes',action='store_true');uninstall.add_argument('--authorizer',choices=['sudo','pkexec'],default='sudo')
    setup=sub.add_parser('setup');setup.add_argument('--role',type=role,choices=['client','server']);setup.add_argument('--peer-profile');setup.add_argument('--yes',action='store_true');setup.add_argument('--update',action='store_true')
    for flag in ('skip-packages','skip-root','no-start','no-integrate'):setup.add_argument('--'+flag,action='store_true')
    pair=sub.add_parser('pair');ps=pair.add_subparsers(dest='pair_action',required=True)
    exp=ps.add_parser('export');exp.add_argument('--role',type=role,choices=['client','server']);exp.add_argument('--output')
    show=ps.add_parser('show');show.add_argument('file')
    for action in ('start','stop','restart','status'):sub.add_parser(action)
    sub.add_parser('server-start')
    link=sub.add_parser('link');link.add_argument('--peer-host-key',required=True)
    root=sub.add_parser('root-plan');root.add_argument('--peer-key',required=True);root.add_argument('--output',required=True)
    for name,choices in [('control',['start','stop','status']),('shot',['serve','request','status'])]:
        sp=sub.add_parser(name);sp.add_argument('action',choices=choices)
    for name in ('files','receive','gallery','session-start','page-native'):sub.add_parser(name)
    battery=sub.add_parser('battery');battery.add_argument('--once',action='store_true')
    send=sub.add_parser('send-code');send.add_argument('file');send.add_argument('--name')
    batch=sub.add_parser('send-files');batch.add_argument('files',nargs='+')
    sub.add_parser('remote-files')
    tr=sub.add_parser('trigger');tr.add_argument('action',choices=['start','shot','kill']);tr.add_argument('phase',choices=['down','up'],default='down',nargs='?')
    args=p.parse_args()
    try:
        if args.command=='init':initialize(args);return 0
        if args.command=='setup':
            from .setup import wizard
            return wizard(args)
        if args.command=='pair':
            from .pairing import export,read,fingerprint
            if args.pair_action=='show':
                value=read(args.file);print(json.dumps(value,ensure_ascii=False,indent=2));print('Код сверки:',fingerprint(value))
            else:export(args.role or load(args.config).role,args.output)
            return 0
        cfg=load(args.config)
        c=args.command
        if c=='uninstall':
            from .uninstall import run
            run(cfg,args.yes,args.authorizer);return 0
        if cfg.role=='server' and c in {'shot','files','battery','session-start','trigger','page-native'}:
            raise ValueError('this command requires role client')
        if cfg.role=='client' and c in {'receive','gallery','send-code','send-files','remote-files'}:
            raise ValueError('this command requires role server')
        if c=='doctor':return doctor(cfg)
        if c=='check':
            from .diagnostics import check
            return check(cfg)
        if c in {'start','stop','restart','status'}:
            from .control import execute
            print(json.dumps(execute(cfg,c),ensure_ascii=False,indent=2));return 0
        if c=='server-start':
            if cfg.role!='server':raise ValueError('server role required')
            subprocess.run(['systemctl','--user','import-environment','WAYLAND_DISPLAY','HYPRLAND_INSTANCE_SIGNATURE','XDG_CURRENT_DESKTOP'],check=True,timeout=3)
            if not cfg.stopped.exists():
                from .control import execute
                execute(cfg,'start')
            return 0
        if c=='link':
            from .install import link
            link(cfg,Path(args.peer_host_key));return 0
        if c=='install-user':
            from .install import user_install
            user_install(cfg,Path(args.config or default_path()).resolve())
        elif c=='root-plan':
            from .install import root_plan
            root_plan(cfg,Path(args.config or default_path()).resolve(),Path(args.peer_key),Path(args.output))
        elif c=='control':
            from .control import execute
            print(json.dumps(execute(cfg,args.action),ensure_ascii=False,indent=2))
        elif c=='shot':
            if args.action=='serve':
                from .screenshots import serve
                serve(cfg)
            else:print(json.dumps(rpc(cfg.runtime/'bridge-shot-queue.sock','shot' if args.action=='request' else args.action)))
        elif c in {'files','gallery'}:
            if c=='files':from .files import serve
            else:from .gallery import serve
            serve(cfg)
        elif c=='page-native':
            from .pages import native
            native(cfg)
        elif c=='receive':
            from .receiver import receive
            receive(cfg)
        elif c=='battery':
            from .display import battery
            battery(cfg,args.once)
        elif c=='send-code':
            from .files import push
            push(cfg,args.file,args.name)
        elif c=='send-files':
            from .files import push_many
            push_many(cfg,args.files)
        elif c=='remote-files':
            from .files import remote_files
            remote_files(cfg)
        elif c=='trigger':trigger(cfg,args.action,args.phase)
        elif c=='session-start':
            subprocess.run(['systemctl','--user','import-environment','WAYLAND_DISPLAY','HYPRLAND_INSTANCE_SIGNATURE','XDG_CURRENT_DESKTOP'],check=True,timeout=3)
            if not cfg.stopped.exists():subprocess.run(['systemctl','--user','start','bridge-start.service'],check=True,timeout=15)
        return 0
    except KeyboardInterrupt:
        print('Отменено. Повторите setup, чтобы продолжить.',file=sys.stderr);return 130
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as e:
        print(type(e).__name__+': '+str(e),file=sys.stderr);return 1
