"""Small Linux primitives shared by all workers."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time

def atomic(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.partial-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
        d=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(d)
        finally:os.close(d)
    finally:Path(temp).unlink(missing_ok=True)

def notify(message):
    address=os.environ.get('NOTIFY_SOCKET')
    if not address:return
    if address.startswith('@'):address='\0'+address[1:]
    with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as s:
        try:s.connect(address);s.sendall(message.encode())
        except OSError:pass

def signals():
    def stop(signum,frame):raise SystemExit(0)
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)

def rpc(path,command):
    payload=(command+'\n').encode()
    for attempt in range(20):
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
            s.settimeout(2)
            try:s.connect(str(path))
            except (FileNotFoundError,ConnectionRefusedError):
                if attempt==19:raise RuntimeError('service is not ready')
                time.sleep(.05);continue
            s.sendall(payload)
            response=bytearray()
            while b'\n' not in response:
                block=s.recv(4096)
                if not block:raise RuntimeError('incomplete service response')
                response.extend(block)
                if len(response)>16384:raise RuntimeError('service response too large')
        result=json.loads(bytes(response).split(b'\n',1)[0])
        if not isinstance(result,dict):raise RuntimeError('invalid service response')
        if not result.get('ok',False):raise RuntimeError(result.get('error','request rejected'))
        return result

def read_command(conn):
    conn.settimeout(.25)
    data=bytearray()
    while b'\n' not in data:
        block=conn.recv(64)
        if not block:raise ValueError('incomplete request')
        data.extend(block)
        if len(data)>64:raise ValueError('request too long')
    return bytes(data).split(b'\n',1)[0].decode('ascii')

def respond(conn,data):
    conn.sendall((json.dumps(data)+'\n').encode())

def listener(path):
    path=Path(path);path.unlink(missing_ok=True)
    s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
    s.bind(str(path));path.chmod(0o600);s.listen(16);s.settimeout(.5)
    return s


def decode_json(data):
    """Reject ambiguous/non-finite JSON and turn excessive depth into a protocol error."""
    text=data.decode('utf-8') if isinstance(data,(bytes,bytearray)) else data
    depth=0;quoted=False;escaped=False
    for char in text:
        if quoted:
            if escaped:escaped=False
            elif char=='\\':escaped=True
            elif char=='"':quoted=False
        elif char=='"':quoted=True
        elif char in '[{':
            depth+=1
            if depth>64:raise ValueError('JSON nesting limit exceeded')
        elif char in ']}':depth-=1
    def pairs(values):
        result={}
        for key,value in values:
            if key in result:raise ValueError('duplicate JSON field')
            result[key]=value
        return result
    def constant(value):raise ValueError('non-finite JSON value')
    try:return json.loads(data,object_pairs_hook=pairs,parse_constant=constant)
    except (RecursionError,MemoryError) as error:raise ValueError('JSON nesting or resource limit exceeded') from error

def receive_limits():
    """Bound only a dedicated native/SSH child, never the desktop or sshd parent."""
    import resource
    ceiling=768*1024*1024
    soft,hard=resource.getrlimit(resource.RLIMIT_AS)
    if soft!=resource.RLIM_INFINITY:ceiling=min(ceiling,soft)
    if hard!=resource.RLIM_INFINITY:ceiling=min(ceiling,hard)
    resource.setrlimit(resource.RLIMIT_AS,(ceiling,hard))
