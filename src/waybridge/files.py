"""Atomic SFTP push and local inotify projection preserving original names."""
import fcntl
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import stat
import subprocess
import tempfile
import time
import uuid
from .runtime import atomic,signals,notify

NAME=re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}')
SUFFIXES={'.py','.cpp','.c','.h','.hpp','.rs','.js','.ts','.java','.go','.sh','.txt','.json'}
LIMIT=32*1024*1024
DELIVERY=re.compile(r'\.delivery-([a-f0-9]{32})\.json')

def sftp(batch,timeout=45):
    return subprocess.run(['sftp','-q','-o','ConnectTimeout=5','-o','ServerAliveInterval=3',
                           '-o','ServerAliveCountMax=2','-b','-','bridge-inbox'],
                          input=batch,text=True,timeout=timeout,capture_output=True)

def transfer_error(detail):
    detail=detail.strip()[-600:]
    if any(text in detail.lower() for text in ('host key verification failed','remote host identification has changed','permission denied (publickey','no such identity')):
        return 'SSH не прошёл проверку ключей. Выполните waybridge check; при смене ПК повторите setup с проверенным профилем. '+detail
    return 'Клиент недоступен или SFTP отклонил загрузку. На ноутбуке выполните waybridge start (Numpad 7), затем waybridge check. Исходник на ПК сохранён. '+detail


def receipt(cfg,identifier,data):
    folder=cfg.inbox/'.receipts';folder.mkdir(mode=0o2750,exist_ok=True)
    if folder.is_symlink() or folder.stat().st_uid!=os.getuid():raise ValueError('небезопасная папка подтверждений')
    path=folder/(identifier+'.json')
    atomic(path,json.dumps({'id':identifier,**data},ensure_ascii=False).encode())
    path.chmod(0o640)
    # Keep bounded confirmation history; each transfer has its own UUID.
    records=[]
    for item in folder.glob('*.json'):
        try:records.append((item.stat().st_mtime_ns,item))
        except OSError:continue
    for _,old in sorted(records)[:-256]:
        if re.fullmatch(r'[a-f0-9]{32}\.json',old.name):
            try:old.unlink(missing_ok=True)
            except OSError:pass

def wait_receipt(identifier,expected,folder,expected_name):
    target=Path(folder)/'receipt.json'
    batch=f'get /inbox/.receipts/{identifier}.json "{target}"\n'
    for delay in (0,.1,.3,.6,1,2):
        if delay:time.sleep(delay)
        target.unlink(missing_ok=True)
        try:
            r=sftp(batch,timeout=5)
            if r.returncode or not target.exists():continue
            if target.stat().st_size>1024:continue
            value=json.loads(target.read_text())
            if not isinstance(value,dict):continue
            if value.get('id')!=identifier or value.get('sha256')!=expected:continue
            if value.get('name')!=expected_name:continue
            if value.get('ok') is True:return
            if value.get('ok') is False:raise RuntimeError('Клиент не сохранил файл: '+str(value.get('error','неизвестная ошибка')))
        except (OSError,ValueError,subprocess.TimeoutExpired):continue
    raise RuntimeError('Файл загружен в SFTP, но сохранение в папке клиента не подтверждено. Проверьте waybridge check на клиенте; исходник сохранён.')

def push(cfg,source,name=None):
    source=Path(source);name=name or source.name
    if not NAME.fullmatch(name):raise ValueError('ASCII filename required')
    if Path(name).suffix not in SUFFIXES:raise ValueError('unsupported destination extension: '+name)
    with source.open('rb') as f:data=f.read(LIMIT+1)
    if len(data)>LIMIT:raise ValueError('file exceeds 32 MiB')
    cfg.state.mkdir(parents=True,exist_ok=True)
    with (cfg.state/'push.lock').open('w') as lock,tempfile.TemporaryDirectory(prefix='waybridge-push-') as td:
        deadline=time.monotonic()+5
        while True:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
            except BlockingIOError:
                if time.monotonic()>=deadline:raise RuntimeError('Другая отправка ещё выполняется. Повторите команду после её завершения.')
                time.sleep(.05)
        local=Path(td)/'payload';local.write_bytes(data);identifier=uuid.uuid4().hex
        digest=hashlib.sha256(data).hexdigest()
        marker=Path(td)/'delivery.json';marker.write_text(json.dumps({'id':identifier,'name':name,'sha256':digest}))
        batch=f'put -f "{local}" /inbox/.partial-{identifier}\nrename /inbox/.partial-{identifier} /inbox/{name}\nput -f "{marker}" /inbox/.partial-meta-{identifier}\nrename /inbox/.partial-meta-{identifier} /inbox/.delivery-{identifier}.json\n'
        detail='Сервер не ответил за отведённое время.'
        for attempt in range(3):
            try:
                r=sftp(batch)
                if r.returncode==0:
                    wait_receipt(identifier,digest,td,name)
                    return
                detail=(r.stderr or r.stdout or 'SFTP завершился с кодом '+str(r.returncode)).strip()
                if any(text in detail.lower() for text in ('host key verification failed','remote host identification has changed','permission denied (publickey','no such identity')):break
            except subprocess.TimeoutExpired:detail='Время ожидания SFTP истекло.'
            if attempt<2:time.sleep(2**attempt)
    raise RuntimeError(transfer_error(detail))

def push_many(cfg,sources):
    paths=[Path(source).expanduser() for source in sources]
    # Validate the entire batch before delivering its first file.
    for path in paths:
        if not path.is_file():raise ValueError('not a regular file: '+str(path))
        if not NAME.fullmatch(path.name):raise ValueError('ASCII filename required: '+path.name)
        if path.suffix not in SUFFIXES:raise ValueError('unsupported file extension: '+path.name)
        if path.stat().st_size>LIMIT:raise ValueError('file exceeds 32 MiB: '+path.name)
    for path in paths:
        push(cfg,path)
        print('Отправлено: '+path.name+' → клиент',flush=True)

def remote_files(cfg):
    result=subprocess.run(['sftp','-q','-b','-','bridge-inbox'],input='ls -lh /inbox\n',text=True,timeout=12)
    if result.returncode:raise RuntimeError('не удалось открыть входящую папку клиента; проверьте waybridge check')

def watch(folder):
    child=subprocess.Popen(['inotifywait','-m','-e','moved_to,close_write,delete','--format','%f',str(folder)],
                           stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                           env={**os.environ,'LC_ALL':'C'})
    for line in child.stderr:
        if 'Watches established.' in line:return child
    child.wait();raise RuntimeError('inotify watch failed')

def publish(cfg,name,identifier=None,expected=None):
    if not NAME.fullmatch(name):return False
    source=cfg.inbox/name
    if source.suffix not in SUFFIXES:return False
    try:
        fd=os.open(source,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):return False
            data=f.read(LIMIT+1)
    except OSError:return False
    if len(data)>LIMIT:return False
    digest=hashlib.sha256(data).hexdigest()
    if expected is not None and digest!=expected:raise ValueError('содержимое входящего файла не соответствует заявке')
    target=cfg.projects/name
    if target.is_file() and not target.is_symlink():
        with target.open('rb') as f:old=f.read(LIMIT+1)
        if len(old)>LIMIT:raise ValueError('existing project file exceeds backup limit; preserving original')
        if old!=data:
            previous_digest=hashlib.sha256(old).hexdigest()[:16]
            atomic(cfg.state/'versions'/(name+'.'+previous_digest),old)
            atomic(target,data)
    else:atomic(target,data)
    if identifier:receipt(cfg,identifier,{'ok':True,'name':name,'size':len(data),'sha256':digest})
    return True

def delivery(cfg,name):
    match=DELIVERY.fullmatch(name)
    if not match:return None
    fd=os.open(cfg.inbox/name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):raise ValueError('regular delivery metadata required')
        raw=stream.read(1025)
    if len(raw)>1024:raise ValueError('delivery metadata too large')
    value=json.loads(raw)
    if not isinstance(value,dict) or value.get('id')!=match[1]:raise ValueError('invalid delivery ID')
    destination=value.get('name');digest=value.get('sha256')
    if not isinstance(destination,str) or not NAME.fullmatch(destination) or Path(destination).suffix not in SUFFIXES:raise ValueError('invalid delivery filename')
    if not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest):raise ValueError('invalid delivery hash')
    return value

def publish_safely(cfg,name):
    value=None
    try:
        if not (cfg.inbox/name).exists():return False
        value=delivery(cfg,name)
        if value:
            result=publish(cfg,value['name'],value['id'],value['sha256'])
            if not result:raise ValueError('входящий файл недоступен или отклонён')
            (cfg.inbox/name).unlink(missing_ok=True)
            return True
        return publish(cfg,name)
    except (OSError,ValueError) as error:
        print('File rejected: '+name+': '+type(error).__name__+': '+str(error),flush=True)
        detail=str(error)
        if isinstance(error,IsADirectoryError):detail='Вместо файла на клиенте существует папка. Переименуйте её или отправьте файл под другим именем.'
        elif isinstance(error,PermissionError):detail='Нет прав на сохранение файла в папке клиента. Проверьте владельца и разрешения.'
        elif isinstance(error,OSError) and error.errno==errno.ENOSPC:detail='На клиенте закончилось свободное место.'
        elif isinstance(error,OSError) and error.errno==errno.EROFS:detail='Файловая система клиента доступна только для чтения.'
        # Keep the failed transaction for retry; other files continue normally.
        if value:
            try:receipt(cfg,value['id'],{'ok':False,'name':value['name'],'sha256':value['sha256'],'error':detail[:300]})
            except OSError:pass
        return False

def file_signature(path):
    try:
        info=path.lstat()
        if stat.S_ISREG(info.st_mode):return info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns
    except FileNotFoundError:pass
    return None

def eligible(name):
    return bool(DELIVERY.fullmatch(name) or (NAME.fullmatch(name) and Path(name).suffix in SUFFIXES))

def process_event(cfg,name,seen):
    if not eligible(name):return
    signature=file_signature(cfg.inbox/name)
    seen.pop(name,None)
    if publish_safely(cfg,name) and signature is not None:seen[name]=signature

def reconcile(cfg,seen):
    """Stat-only scan repairs missed events; unchanged files are not recopied."""
    current={}
    for path in cfg.inbox.iterdir():
        if not eligible(path.name):continue
        signature=file_signature(path)
        if signature is None:continue
        current[path.name]=signature
        # Failed transactions stay eligible, so repairing a destination needs no re-upload.
        if seen.get(path.name)!=signature:
            if not publish_safely(cfg,path.name):current.pop(path.name,None)
    return current

def serve(cfg):
    signals();cfg.projects.mkdir(parents=True,exist_ok=True);cfg.state.mkdir(parents=True,exist_ok=True)
    child=watch(cfg.inbox);selector=selectors.DefaultSelector()
    os.set_blocking(child.stdout.fileno(),False);selector.register(child.stdout,selectors.EVENT_READ)
    pending=b'';seen={}
    try:
        notify('READY=1\nSTATUS=File watcher ready')
        seen=reconcile(cfg,seen)
        deadline=time.monotonic()+15
        while True:
            rescan=False
            for key,_ in selector.select(max(0,min(1,deadline-time.monotonic()))):
                block=os.read(key.fileobj.fileno(),65536)
                if not block:raise RuntimeError('inotify process exited')
                pending+=block
                while b'\n' in pending:
                    name,pending=pending.split(b'\n',1)
                    name=name.decode('utf-8',errors='replace')
                    if not name:rescan=True;continue  # e.g. inotify overflow
                    process_event(cfg,name,seen)
            if rescan or time.monotonic()>=deadline:
                seen=reconcile(cfg,seen);deadline=time.monotonic()+15
    finally:
        selector.close();child.terminate();child.wait(timeout=2)
