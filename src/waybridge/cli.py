"""Explicit command interface; imports never start workers or intercept input."""
import argparse
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import time
from .config import load, default_path
from .runtime import atomic, rpc

def initialize(args):
    own=subprocess.check_output(['tailscale','ip','-4'],text=True,timeout=3).strip()
    user=pwd.getpwuid(os.getuid()).pw_name
    data={'role':args.role,'own_ip':own,'peer_ip':args.peer_ip,'user':user,
          'helper_user':args.helper_user or user,'hold_ms':0}
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
    # Compositor press/release bindings, matching physical pad behavior under grab.
    stamp=cfg.runtime/('waybridge-hold-'+action)
    if phase=='down' and cfg.hold_ms and action!='kill':
        atomic(stamp,str(time.monotonic()).encode());return
    if phase=='up':
        try:elapsed=time.monotonic()-float(stamp.read_text())
        except (OSError,ValueError):return
        stamp.unlink(missing_ok=True)
        if elapsed<cfg.hold_ms/1000:return
    if action in {'start','kill'}:
        subprocess.run(['systemctl','--user','start','--no-block',
                        'bridge-start.service' if action=='start' else 'bridge-kill.service'],check=True,timeout=2)
    elif action=='shot':print(json.dumps(rpc(cfg.runtime/'bridge-shot-queue.sock','shot')))
    elif action=='input':print(json.dumps(rpc(cfg.runtime/'bridge-key-code.sock','toggle')))
    else:
        from .display import clock_control
        clock_control(cfg,'reset' if action=='reset' else 'toggle')

def doctor(cfg):
    import shutil
    commands=['tailscale','ssh','sftp','systemctl','inotifywait']
    commands+=['hyprctl','grim','ydotool'] if cfg.role=='client' else ['imv-wayland','imv-msg']
    results={x:bool(shutil.which(x)) for x in commands}
    if cfg.role=='client':
        results['keyboard-readable']=os.access(cfg.keyboard,os.R_OK)
        results['inbox-readable']=os.access(cfg.inbox,os.R_OK)
    results['runtime-directory']=bool(os.environ.get('XDG_RUNTIME_DIR'))
    print(json.dumps(results,ensure_ascii=False,indent=2))
    return 0 if all(results.values()) else 1

def main():
    p=argparse.ArgumentParser(prog='waybridge');p.add_argument('--config')
    sub=p.add_subparsers(dest='command',required=True)
    init=sub.add_parser('init');init.add_argument('--role',choices=['client','helper'],required=True);init.add_argument('--peer-ip',required=True);init.add_argument('--helper-user')
    sub.add_parser('doctor');sub.add_parser('install-user')
    link=sub.add_parser('link');link.add_argument('--peer-host-key',required=True)
    root=sub.add_parser('root-plan');root.add_argument('--peer-key',required=True);root.add_argument('--output',required=True)
    for name,choices in [('control',['start','stop','status','reset']),('input',['serve','toggle','stop','status']),('shot',['serve','request','status']),('clock',['serve','reset','toggle'])]:
        sp=sub.add_parser(name);sp.add_argument('action',choices=choices)
    for name in ('files','receive','gallery','notes','release','session-start'):sub.add_parser(name)
    battery=sub.add_parser('battery');battery.add_argument('--once',action='store_true')
    send=sub.add_parser('send-code');send.add_argument('file');send.add_argument('--name')
    ans=sub.add_parser('send-answer');ans.add_argument('number',type=int);ans.add_argument('answer',type=int)
    tr=sub.add_parser('trigger');tr.add_argument('action',choices=['start','shot','kill','input','reset','clock']);tr.add_argument('phase',choices=['down','up'],default='down',nargs='?')
    args=p.parse_args()
    try:
        if args.command=='init':initialize(args);return 0
        cfg=load(args.config)
        c=args.command
        if cfg.role=='helper' and c in {'control','input','shot','clock','files','notes','battery','release','session-start','trigger'}:
            raise ValueError('this command requires role client')
        if cfg.role=='client' and c in {'receive','gallery','send-code','send-answer'}:
            raise ValueError('this command requires role helper')
        if c=='doctor':return doctor(cfg)
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
        elif c in {'input','shot'}:
            if args.action=='serve':
                if c=='input':from .keyboard import serve
                else:from .screenshots import serve
                serve(cfg)
            else:print(json.dumps(rpc(cfg.runtime/('bridge-key-code.sock' if c=='input' else 'bridge-shot-queue.sock'),'shot' if args.action=='request' else args.action)))
        elif c=='clock':
            from .display import clock,clock_control
            clock(cfg) if args.action=='serve' else clock_control(cfg,args.action)
        elif c in {'files','gallery'}:
            if c=='files':from .files import serve
            else:from .gallery import serve
            serve(cfg)
        elif c=='receive':
            from .receiver import receive
            receive(cfg)
        elif c=='notes':
            from .display import notes
            notes(cfg)
        elif c=='battery':
            from .display import battery
            battery(cfg,args.once)
        elif c in {'send-code','send-answer'}:
            from .files import push,answer
            push(cfg,args.file,args.name) if c=='send-code' else answer(cfg,args.number,args.answer)
        elif c=='release':
            from .inject import Emitter
            Emitter().release()
        elif c=='trigger':trigger(cfg,args.action,args.phase)
        elif c=='session-start':
            subprocess.run(['systemctl','--user','import-environment','WAYLAND_DISPLAY','HYPRLAND_INSTANCE_SIGNATURE','XDG_CURRENT_DESKTOP'],check=True,timeout=3)
            if not cfg.stopped.exists():subprocess.run(['systemctl','--user','start','bridge-start.service'],check=True,timeout=15)
        return 0
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as e:
        print(type(e).__name__+': '+str(e),file=sys.stderr);return 1
