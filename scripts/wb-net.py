#!/usr/bin/env python3
"""Send a numeric Waybar display value through the existing file transport."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

def main():
    parser=argparse.ArgumentParser(description='wb-net НОМЕР ОТВЕТ | wb-net clear')
    parser.add_argument('values',nargs='+');args=parser.parse_args()
    data={'schema':'waybar-network/1','active':False}
    if args.values!=['clear']:
        if len(args.values)!=2:parser.error('нужны номер и ответ, либо clear')
        try:number,answer=map(int,args.values)
        except ValueError:parser.error('номер и ответ должны быть целыми числами')
        if not 0<=number<=999 or not 0<=answer<=999:parser.error('допустимы значения 0–999')
        data.update(active=True,number=number,answer=answer)
    with tempfile.TemporaryDirectory(prefix='wb-network-') as folder:
        source=Path(folder)/'network-display.json';source.write_text(json.dumps(data)+'\n')
        result=subprocess.run([str(Path.home()/'.local/bin/waybridge'),'send-code',str(source),'--name','network-display.json'])
        if result.returncode:return result.returncode
    print('Отправлен сброс к реальной скорости.' if not data['active'] else f'Отправлено: ↓ {number:02} ↑ {answer:02}')
    return 0

if __name__=='__main__':raise SystemExit(main())
