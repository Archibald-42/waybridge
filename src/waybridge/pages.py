"""Bounded, read-only page snapshots over the existing pinned SSH endpoint."""
import base64
import binascii
import fcntl
import hashlib
from html import escape
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import time
from .protocol import LIMIT,frame,parse,validate_png,verify_ack
from .runtime import atomic,signals

MAGIC=b'WBP1'
EXTENSION_ID='page-export@waybridge.local'
HOST_NAME='org.waybridge.page_export'
MAX_PIXELS=80_000_000

def text(value,limit=16384):
    if not isinstance(value,str) or len(value)>limit:raise ValueError('invalid or oversized text')
    return value

def integer(value,low,high):
    if type(value) is not int or not low<=value<=high:raise ValueError('invalid image geometry')
    return value

def sequence(value,limit):
    if not isinstance(value,list) or len(value)>limit:raise ValueError('invalid or oversized list')
    return value

def mapping(value,keys):
    if not isinstance(value,dict) or set(value)!=set(keys.split()):raise ValueError('invalid snapshot fields')
    return value

def validate(data):
    if not 0<len(data)<=LIMIT:raise ValueError('page snapshot exceeds 32 MiB')
    doc=json.loads(data)
    mapping(doc,'format id created_at scope page tiles warnings')
    if doc['format']!='waybridge-page/1' or doc['scope']!='current-section':raise ValueError('unsupported snapshot format/scope')
    if not isinstance(doc['id'],str) or not re.fullmatch('[a-f0-9]{32}',doc['id']):raise ValueError('invalid snapshot id')
    text(doc['created_at'],64)
    page=mapping(doc['page'],'title url text questions fields images geometry')
    text(page['title']);text(page['url'],8192);text(page['text'],2_000_000)
    geometry=mapping(page['geometry'],'width height scrollX scrollY viewportWidth viewportHeight')
    width=integer(geometry['width'],1,8192);height=integer(geometry['height'],1,100000)
    if width*height>MAX_PIXELS:raise ValueError('page exceeds 80 million CSS pixels')
    for name in ('scrollX','scrollY'):integer(geometry[name],0,100000)
    for name in ('viewportWidth','viewportHeight'):integer(geometry[name],1,16384)
    for question in sequence(page['questions'],1000):
        mapping(question,'id title text options');text(question['id'],64);text(question['title']);text(question['text'],100000)
        for option in sequence(question['options'],1000):
            mapping(option,'id kind label selected')
            for key in ('id','kind','label'):text(option[key])
            if type(option['selected']) is not bool:raise ValueError('invalid selected state')
    for field in sequence(page['fields'],2000):
        mapping(field,'kind label value checked')
        for key in ('kind','label','value'):text(field[key],100000)
        if field['checked'] is not None and type(field['checked']) is not bool:raise ValueError('invalid checked state')
    for image in sequence(page['images'],1000):
        mapping(image,'alt x y width height loaded');text(image['alt'])
        for key in ('x','y','width','height'):integer(image[key],0,100000)
        if type(image['loaded']) is not bool:raise ValueError('invalid loaded state')
    for warning in sequence(doc['warnings'],100):text(warning)
    tiles=sequence(doc['tiles'],32)
    if not tiles:raise ValueError('visual reference is required')
    next_y=0
    for tile in tiles:
        mapping(tile,'x y width height png')
        if type(tile['x']) is not int or tile['x']!=0 or type(tile['y']) is not int or tile['y']!=next_y:raise ValueError('visual tiles overlap or have gaps')
        if type(tile['width']) is not int or tile['width']!=width:raise ValueError('tile width mismatch')
        tile_height=integer(tile['height'],1,4096)
        if not isinstance(tile['png'],str) or not tile['png'].startswith('data:image/png;base64,'):raise ValueError('only embedded PNG is accepted')
        try:png=base64.b64decode(tile['png'][22:],validate=True)
        except (ValueError,binascii.Error) as error:raise ValueError('invalid embedded PNG') from error
        validate_png(png)
        if struct.unpack('>II',png[16:24])!=(width,tile_height):raise ValueError('PNG dimensions do not match tile geometry')
        next_y+=tile_height
    if next_y!=height:raise ValueError('visual reference does not cover the entire section')
    return doc

def encode(doc):
    data=json.dumps(doc,ensure_ascii=False,separators=(',',':'),sort_keys=True).encode()
    validate(data)
    return data

def render(doc):
    """Render only escaped text and validated inline PNG; never source HTML/JS."""
    page=doc['page'];out=['<!doctype html><html lang="ru"><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">',
        '<title>'+escape(page['title'])+' — Waybridge</title>',
        '<style>body{font:17px/1.55 system-ui,sans-serif;max-width:1100px;margin:36px auto;padding:0 22px;color:#182030;background:#f5f7fa}h1{line-height:1.2}article,details,figure{background:white;border:1px solid #d4dce8;border-radius:12px;padding:20px;margin:18px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}li{margin:10px 0}img{display:block;width:100%;height:auto}small,figcaption{color:#536078}nav a{margin-right:18px}code{overflow-wrap:anywhere}summary{cursor:pointer}.warning{border-left:5px solid #b66a08;padding:12px;background:#fff2d8}.selected{font-weight:700}</style>',
        '<h1>'+escape(page['title'])+'</h1>',
        '<p><strong>Снимок текущего раздела.</strong> Следующие разделы не включены.</p>',
        '<p><code>'+escape(page['url'])+'</code><br><small>'+escape(doc['created_at'])+' · '+escape(doc['id'])+'</small></p>',
        '<nav><a href="#questions">Вопросы</a><a href="#fields">Состояние полей</a><a href="#original">Оригинальный вид</a><a href="#text">Весь текст</a></nav>']
    for warning in doc['warnings']:out.append('<p class="warning">'+escape(warning)+'</p>')
    out.append('<h2 id="questions">Вопросы в исходном порядке</h2>')
    if not page['questions']:out.append('<p>Отдельные вопросы не распознаны. Используйте оригинальный вид и весь текст ниже.</p>')
    for index,question in enumerate(page['questions'],1):
        out.append('<article><h3>'+str(index)+'. '+escape(question['title'])+'</h3><pre>'+escape(question['text'])+'</pre><ol>')
        for option in question['options']:
            selected=option['selected'];out.append('<li'+(' class="selected"' if selected else '')+'>'+('✓ ' if selected else '')+escape(option['label'])+'</li>')
        out.append('</ol><small>Идентификатор внутри снимка: '+escape(question['id'])+'</small></article>')
    out.append('<h2 id="fields">Состояние полей</h2><ul>')
    for field in page['fields']:
        value=('✓ ' if field['checked'] else '□ ') if field['checked'] is not None else ''
        out.append('<li>'+escape(field['label'])+': '+escape(value+field['value'])+'</li>')
    out.append('</ul><h2 id="original">Оригинальный вид всего раздела</h2>')
    for index,tile in enumerate(doc['tiles'],1):
        out.append('<figure><figcaption>Фрагмент '+str(index)+' · y='+str(tile['y'])+'</figcaption><img alt="Снимок раздела, фрагмент '+str(index)+'" src="'+tile['png']+'"></figure>')
    out.append('<details id="text"><summary>Весь доступный текст раздела</summary><pre>'+escape(page['text'])+'</pre></details></html>')
    return ''.join(out).encode()

def receive(cfg,stream,first):
    header,data=parse(stream,first,magic=MAGIC,validator=validate)
    if header is None:raise ValueError('page frame required')
    doc=json.loads(data)
    if doc['id']!=header['id']:raise ValueError('snapshot id does not match envelope')
    folder=cfg.state/'pages';folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    identifier=header['id'];target=folder/(identifier+'.json')
    with (folder/'.receive.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()!=header['sha256']:raise ValueError('page id reused with different content')
        if not target.exists():atomic(target,data)
        view=folder/(identifier+'.html')
        if not view.exists():atomic(view,render(doc))
        atomic(folder/'latest.json',json.dumps({'id':identifier}).encode())
        # Retention is deterministic and never removes unrelated names.
        entries=sorted((p for p in folder.glob('*.html') if re.fullmatch(r'[a-f0-9]{32}\.html',p.name)),key=lambda p:p.stat().st_mtime_ns)
        for old in entries[:-10]:
            if old.stem==identifier:continue
            old.unlink(missing_ok=True);old.with_suffix('.json').unlink(missing_ok=True)
    print(json.dumps({'ok':True,**header}),flush=True)

def send(cfg,doc):
    if cfg.stopped.exists():raise RuntimeError('Клиент остановлен. Запустите Waybridge: Win+X.')
    data=encode(doc)
    packet,header=frame(doc['id'],data,magic=MAGIC)
    error='Нет подтверждения приёмника. Обновите Waybridge на обоих ПК до 3.6.0.'
    for attempt in range(3):
        if cfg.stopped.exists():raise RuntimeError('Передача отменена: Waybridge остановлен.')
        proc=subprocess.Popen(['ssh','-T','-o','ConnectTimeout=5','bridge-shot'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        deadline=time.monotonic()+45;initial=True
        try:
            while True:
                if cfg.stopped.exists():raise RuntimeError('Передача отменена: Waybridge остановлен.')
                if time.monotonic()>=deadline:raise subprocess.TimeoutExpired('page transfer',45)
                try:
                    output,stderr=proc.communicate(input=packet if initial else None,timeout=.2)
                    if proc.returncode==0 and verify_ack(output,header):return {'ok':True,'id':header['id'],'size':len(data)}
                    detail=stderr.decode(errors='replace').strip()[-500:]
                    if detail:error='Приёмник не подтвердил сохранение. '+detail
                    if any(s in detail.lower() for s in ('host key verification failed','remote host identification has changed','permission denied (publickey')):raise RuntimeError(error)
                    break
                except subprocess.TimeoutExpired:initial=False
        except subprocess.TimeoutExpired:error='Истекло время доставки. Снимок можно отправить повторно.'
        finally:
            if proc.poll() is None:
                proc.kill();proc.communicate()
        if attempt<2:
            until=time.monotonic()+2**attempt
            while time.monotonic()<until:
                if cfg.stopped.exists():raise RuntimeError('Передача отменена: Waybridge остановлен.')
                time.sleep(.1)
    raise RuntimeError(error)

def read_exact(stream,size):
    data=bytearray()
    while len(data)<size:
        block=stream.read(size-len(data))
        if not block:raise ValueError('truncated native message')
        data.extend(block)
    return bytes(data)

def native(cfg,source=None,destination=None):
    import sys
    if source is None:signals()  # Firefox disconnect cancels SSH through send() finally.
    source=source or sys.stdin.buffer;destination=destination or sys.stdout.buffer
    try:
        size=struct.unpack('=I',read_exact(source,4))[0]
        if not 0<size<=LIMIT+1024:raise ValueError('native message exceeds limit')
        request=json.loads(read_exact(source,size))
        if not isinstance(request,dict) or set(request)!={'action','snapshot'} or request['action']!='send':raise ValueError('unsupported native action')
        result=send(cfg,request['snapshot'])
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:result={'ok':False,'error':str(error)[:1200]}
    output=json.dumps(result,ensure_ascii=False).encode()
    destination.write(struct.pack('=I',len(output))+output);destination.flush()

class PageViewer:
    """Reuse the gallery supervisor; no listener, web server or extra daemon."""
    def __init__(self,cfg):
        self.cfg=cfg;self.last=None;self.next_check=0;self.next_retry=0
        try:
            record=cfg.state/'page-viewer.json'
            if record.stat().st_size<=128:
                data=json.loads(record.read_text())
                value=data.get('requested') if isinstance(data,dict) else None
                if isinstance(value,str) and re.fullmatch('[a-f0-9]{32}',value):self.last=value
        except (OSError,ValueError):pass
    def refresh(self):
        now=time.monotonic()
        if now<self.next_check:return
        self.next_check=now+1
        marker=self.cfg.state/'pages/latest.json'
        try:
            if marker.stat().st_size>128:return
            data=json.loads(marker.read_text())
            identifier=data.get('id') if isinstance(data,dict) else None
            if not isinstance(identifier,str) or not re.fullmatch('[a-f0-9]{32}',identifier):return
            if identifier==self.last or now<self.next_retry:return
            path=marker.parent/(identifier+'.html')
            if not path.is_file() or path.is_symlink():return
            unit='waybridge-page-'+identifier
            existing=subprocess.run(['systemctl','--user','is-active',unit+'.service'],capture_output=True,text=True,timeout=2)
            if (existing.stdout or '').strip()!='active':
                subprocess.run(['systemd-run','--user','--collect','--no-block','--unit='+unit,
                                '--','xdg-open',path.as_uri()],check=True,timeout=5,capture_output=True)
            self.last=identifier
            atomic(self.cfg.state/'page-viewer.json',json.dumps({'requested':identifier}).encode())
        except FileNotFoundError:return
        except (OSError,ValueError,subprocess.SubprocessError) as error:
            self.next_retry=now+15
            print('Page viewer: '+str(error),flush=True)
