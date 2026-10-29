#!/usr/bin/env python3
"""Waybar network rates with an optional, strictly numeric display override."""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time

HOME=Path.home()
PAYLOAD=HOME/'Documents/projects/network-display.json'
BRIDGE=HOME/'.config/waybridge/config.toml'
STOPPED=HOME/'.cache/bridge/stopped'
INTERFACE=re.compile(r'[A-Za-z0-9_.:-]{1,64}')

def override(path=PAYLOAD):
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):return None
            raw=stream.read(1025)
        if len(raw)>1024:return None
        data=json.loads(raw)
        if not isinstance(data,dict) or data.get('schema')!='waybar-network/1' or data.get('active') is not True:return None
        number,answer=data.get('number'),data.get('answer')
        if type(number) is not int or type(answer) is not int:return None
        if not 0<=number<=999 or not 0<=answer<=999:return None
        return number,answer
    except (OSError,ValueError,UnicodeError):return None

def interface():
    try:
        routes=json.loads(subprocess.check_output(['ip','-j','route','show','default'],timeout=1))
        for route in sorted(routes,key=lambda row:row.get('metric',0)):
            name=route.get('dev','')
            if INTERFACE.fullmatch(name) and name!='lo' and (Path('/sys/class/net')/name).exists():return name
    except (OSError,ValueError,subprocess.SubprocessError):pass
    return None

def counters(name):
    root=Path('/sys/class/net')/name/'statistics'
    return int((root/'rx_bytes').read_text()),int((root/'tx_bytes').read_text())

def rate(value,fraction=None):
    value=max(0,float(value))
    for unit in ('B/s','KiB/s','MiB/s','GiB/s'):
        if value<1024 or unit=='GiB/s':
            if fraction is not None:return f'{int(value)}.{fraction:02d} {unit}'
            digits=f'{value:.3f}'
            if digits.endswith('0'):digits=digits[:-1]
            return f'{digits} {unit}'
        value/=1024

class Monitor:
    def __init__(self):self.previous=None
    def sample(self):
        now=time.monotonic();name=interface();down=up=0
        if name:
            try:
                rx,tx=counters(name)
                if self.previous and self.previous[0]==name:
                    _,when,oldrx,oldtx=self.previous
                    seconds=max(.001,now-when)
                    down=max(0,rx-oldrx)/seconds;up=max(0,tx-oldtx)/seconds
                self.previous=(name,now,rx,tx)
            except (OSError,ValueError):name=None;self.previous=None
        else:self.previous=None
        value=override() if BRIDGE.exists() and not STOPPED.exists() else None
        down_text=rate(down,value[0] if value is not None else None)
        up_text=rate(up,value[1] if value is not None else None)
        if not name:return {'text':'Нет сети','tooltip':'Нет маршрута по умолчанию','class':'disconnected'}
        label='Wi-Fi' if (Path('/sys/class/net')/name/'wireless').exists() or name.startswith(('wlan','wlp','wlx')) else 'LAN'
        return {'text':f'{label}  ↓ {down_text}  ↑ {up_text}',
                'tooltip':f'{name}\nПриём: {down_text}\nОтправка: {up_text}','class':'connected'}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--once',action='store_true');args=parser.parse_args()
    monitor=Monitor();deadline=time.monotonic()
    while True:
        print(json.dumps(monitor.sample(),ensure_ascii=False),flush=True)
        if args.once:return
        deadline+=5
        if deadline<time.monotonic():deadline=time.monotonic()
        time.sleep(max(0,deadline-time.monotonic()))

if __name__=='__main__':
    try:main()
    except (KeyboardInterrupt,BrokenPipeError):pass
