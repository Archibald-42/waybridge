"""Explicit physical-key substitution with fail-closed focus/deadline checks."""
import fcntl
import os
from pathlib import Path
import selectors
import struct
import subprocess
import time
from .inject import Emitter
from .runtime import active, listener, notify, read_command, respond, rpc, signals

EVENT=struct.Struct('llHHi')
GRAB=0x40044590
KEY_STATE=0x80604518
PRINTABLE=set(range(2,14))|set(range(16,28))|set(range(30,42))|set(range(43,54))|{15,57}
MODIFIERS={29,56,97,100,125,126}
PAD={71:'start',72:'shot',73:'kill',75:'input',76:'reset',77:'clock'}

class Cursor:
    def __init__(self,code): self.code=code;self.position=0
    def press(self,key):
        if key==14:
            if self.position:self.position-=1;return 'backspace',None
            return None,None
        if self.position==len(self.code):return None,None
        char=self.code[self.position]
        if (char=='\n')!=(key==28):return None,None
        if key!=28 and key not in PRINTABLE:return None,None
        self.position+=1
        return 'character',char

def snapshot(cfg):
    root=cfg.projects.resolve()
    path=Path((cfg.state/'latest-code').read_text()).resolve()
    if path.parent!=root:raise ValueError('code is outside configured projects directory')
    with path.open() as f:code=f.read(100001)
    code=code.replace('\r\n','\n').expandtabs(4)
    if len(code)>100000 or any(c!='\n' and not 32<=ord(c)<=126 for c in code):
        raise ValueError('100000-character ASCII limit; disable editor auto-indent/auto-pairs')
    if not code:raise ValueError('empty code file')
    return path,code

def serve(cfg):
    signals();emitter=Emitter();fd=os.open(cfg.keyboard,os.O_RDONLY|os.O_NONBLOCK)
    endpoint=cfg.runtime/'bridge-key-code.sock';sock=listener(endpoint)
    selector=selectors.DefaultSelector();selector.register(sock,selectors.EVENT_READ);selector.register(fd,selectors.EVENT_READ)
    held=set();state='off';grabbed=False;target=None;cursor=Cursor('');path=None
    last_tick=time.monotonic();checked=0.0;armed_at=0.0;reason='startup';pad_down={}
    def refresh():
        bits=bytearray(96);fcntl.ioctl(fd,KEY_STATE,bits,True)
        held.clear();held.update(k for k in range(768) if bits[k//8]&(1<<(k%8)))
    def drain():
        while True:
            try:
                if not os.read(fd,EVENT.size*128):raise RuntimeError('keyboard disconnected')
            except BlockingIOError:break
        refresh()
    def disable(why='manual'):
        nonlocal state,grabbed,reason
        if grabbed:fcntl.ioctl(fd,GRAB,0);grabbed=False
        state='off';reason=why;emitter.release()
    def arm():
        nonlocal state,target,cursor,path,armed_at,reason
        if cfg.stopped.exists():raise RuntimeError('bridge is stopped')
        disable();path,code=snapshot(cfg);target=active(cfg.api_timeout)
        cursor=Cursor(code);state='arming';armed_at=time.monotonic();reason='waiting for key release'
    def action(name):
        if name=='kill':
            disable('kill switch')
            subprocess.run(['systemctl','--user','start','--no-block','bridge-kill.service'],check=True,timeout=1)
        elif name=='start':
            disable('start requested')
            subprocess.run(['systemctl','--user','start','--no-block','bridge-start.service'],check=True,timeout=1)
        elif name=='shot':rpc(cfg.runtime/'bridge-shot-queue.sock','shot')
        elif name=='input':disable() if state!='off' else arm()
        elif name in {'reset','clock'}:
            from .display import clock_control
            clock_control(cfg,'reset' if name=='reset' else 'toggle')
    refresh();notify('READY=1\nSTATUS=Input OFF')
    try:
        while True:
            events=selector.select(.05);now=time.monotonic()
            if state!='off' and now-last_tick>cfg.loop_limit:
                disable('event loop deadline exceeded');drain()
            last_tick=now;notify('WATCHDOG=1')
            for ready,_ in events:
                if ready.fileobj is sock:
                    conn,_=sock.accept()
                    with conn:
                        try:
                            command=read_command(conn)
                            if command=='toggle':disable() if state!='off' else arm()
                            elif command=='stop':disable()
                            elif command!='status':raise ValueError('invalid command')
                            respond(conn,{'ok':True,'mode':state,'position':cursor.position,'total':len(cursor.code),'reason':reason,'file':path.name if path else None})
                        except Exception as e:
                            disable('control/focus API error')
                            try:respond(conn,{'ok':False,'error':str(e)})
                            except OSError:pass
                    continue
                try:data=os.read(fd,EVENT.size*64)
                except BlockingIOError:continue
                for offset in range(0,len(data),EVENT.size):
                    _,_,kind,key,value=EVENT.unpack_from(data,offset)
                    if kind!=1:continue
                    if state=='active' and time.monotonic()-last_tick>cfg.loop_limit:
                        disable('event packet deadline exceeded');drain();break
                    if value in (1,2):held.add(key)
                    elif value==0:held.discard(key)
                    if grabbed and key in PAD:
                        if value==1:
                            pad_down[key]=time.monotonic()
                            if not cfg.hold_ms or key==73:action(PAD[key])
                        elif value==0 and cfg.hold_ms and key!=73:
                            if time.monotonic()-pad_down.pop(key,time.monotonic())>=cfg.hold_ms/1000:action(PAD[key])
                        continue
                    if state!='active' or value!=1:continue
                    if key==1:disable('Escape');continue
                    if key in MODIFIERS:state='exiting';continue
                    try:
                        if active(cfg.api_timeout)!=target:disable('focus changed');continue
                        operation,char=cursor.press(key)
                        if operation=='character':emitter.emit(char)
                        elif operation=='backspace':emitter.keys(['14:1','14:0'])
                    except Exception:disable('focus/injection API failure')
            now=time.monotonic()
            if state!='off' and now-checked>=.15:
                checked=now
                try:
                    if active(cfg.api_timeout)!=target:disable('focus changed')
                except Exception:disable('focus API unavailable')
            if state=='arming':
                if now-armed_at>5:disable('arming timeout')
                elif not held:fcntl.ioctl(fd,GRAB,1);grabbed=True;state='active'
            elif state=='exiting' and not held:disable('modifier chord')
    finally:
        notify('STOPPING=1');disable('shutdown');os.close(fd);sock.close();endpoint.unlink(missing_ok=True)
