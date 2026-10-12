"""RAM-only FIFO, bounded by count and bytes, with verified retry acknowledgements."""
import json
import queue
import socket
import subprocess
import threading
import time
import uuid
from .protocol import frame,verify_ack,validate_png
from .runtime import listener,notify,read_command,respond,signals

class Budget:
    def __init__(self,count,bytes_limit):
        self.limit=count;self.bytes_limit=bytes_limit;self.count=0;self.bytes=0;self.lock=threading.Lock()
    def reserve(self):
        with self.lock:
            if self.count>=self.limit:return False
            self.count+=1;return True
    def attach(self,size):
        with self.lock:
            if self.bytes+size>self.bytes_limit:return False
            self.bytes+=size;return True
    def release(self,size=0):
        with self.lock:self.count-=1;self.bytes-=size
    def status(self):
        with self.lock:return {'pending':self.count,'bytes':self.bytes}

def serve(cfg):
    signals();requests=queue.Queue(cfg.queue_count);frames=queue.Queue(cfg.queue_count)
    budget=Budget(cfg.queue_count,cfg.queue_bytes);stop=threading.Event()
    def capture():
        while not stop.is_set():
            try:identifier=requests.get(timeout=.2)
            except queue.Empty:continue
            size=0;attached=False
            try:
                monitors=json.loads(subprocess.check_output(['hyprctl','-j','monitors'],timeout=1))
                outputs=[m['name'] for m in monitors if m.get('focused')]
                if len(outputs)!=1:raise RuntimeError('focused monitor not available')
                r=subprocess.run(['grim','-l','1','-o',outputs[0],'-'],capture_output=True,check=True,timeout=8)
                if not 0<len(r.stdout)<=cfg.png_limit:raise RuntimeError('PNG size limit')
                validate_png(r.stdout)
                size=len(r.stdout);attached=budget.attach(size)
                if not attached:raise RuntimeError('RAM byte budget exceeded')
                frames.put((identifier,r.stdout),timeout=1)
            except Exception as e:
                budget.release(size if attached else 0)
                print('capture rejected:',type(e).__name__,flush=True)
            finally:requests.task_done()
    def transmit():
        while not stop.is_set():
            try:identifier,png=frames.get(timeout=.2)
            except queue.Empty:continue
            try:
                packet,header=frame(identifier,png)
                delivered=False
                for attempt in range(3):
                    if stop.is_set():break
                    try:
                        r=subprocess.run(['ssh','-T','bridge-shot'],input=packet,capture_output=True,timeout=30)
                        if r.returncode==0 and verify_ack(r.stdout,header):delivered=True;break
                    except subprocess.TimeoutExpired:pass
                    if stop.wait(min(2**attempt,4)):break
                print('delivery '+('confirmed' if delivered else 'failed')+' id='+identifier,flush=True)
            finally:budget.release(len(png));frames.task_done()
    workers=[threading.Thread(target=capture,daemon=True),threading.Thread(target=transmit,daemon=True)]
    for worker in workers:worker.start()
    endpoint=cfg.runtime/'bridge-shot-queue.sock';sock=listener(endpoint)
    notify('READY=1\nSTATUS=Screenshot queue ready')
    try:
        while True:
            if not all(w.is_alive() for w in workers):raise RuntimeError('worker thread terminated')
            notify('WATCHDOG=1')
            try:conn,_=sock.accept()
            except socket.timeout:continue
            with conn:
                try:
                    command=read_command(conn)
                    if command=='status':respond(conn,{'ok':True,**budget.status()})
                    elif command!='shot':raise ValueError('invalid command')
                    elif cfg.stopped.exists():raise RuntimeError('bridge stopped')
                    elif not budget.reserve():raise RuntimeError('queue count limit reached')
                    else:
                        try:requests.put_nowait(uuid.uuid4().hex)
                        except queue.Full:budget.release();raise RuntimeError('queue full')
                        respond(conn,{'ok':True,**budget.status()})
                except Exception as e:
                    try:respond(conn,{'ok':False,'error':str(e)})
                    except OSError:pass
    finally:
        stop.set();notify('STOPPING=1');sock.close();endpoint.unlink(missing_ok=True)
