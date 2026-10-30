"""Real isolated AF_UNIX recovery while a synthetic frame waits for SSH ACK."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from test_core import png
from waybridge.runtime import rpc

class QueueEndpointRecoveryTests(unittest.TestCase):
    def test_rebind_preserves_inflight_frame_and_ack(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);runtime=root/'runtime';runtime.mkdir();bin=root/'bin';bin.mkdir()
            gate=root/'allow-ack';endpoint=runtime/'bridge-shot-queue.sock'
            config=root/'config.toml'
            values={'role':'client','own_ip':'100.64.0.1','peer_ip':'100.64.0.2','user':'tester','server_user':'tester','state':str(root/'state'),'projects':str(root/'projects'),'inbox':str(root/'inbox')}
            config.write_text(''.join(k+' = '+json.dumps(v)+'\n' for k,v in values.items()))
            (root/'state').mkdir()
            scripts={
              'hyprctl':"print('[{\"focused\":true,\"name\":\"test\"}]')\n",
              'grim':'import sys\nsys.stdout.buffer.write('+repr(png())+')\n',
              'ssh':"import sys,json,time\nfrom pathlib import Path\ndata=sys.stdin.buffer.read()\nheader=json.loads(data[4:].split(b'\\n',1)[0])\ndeadline=time.monotonic()+8\nwhile not Path("+repr(str(gate))+").exists():\n if time.monotonic()>deadline:raise SystemExit(1)\n time.sleep(.02)\nprint(json.dumps({'ok':True,**header}))\n"}
            for name,body in scripts.items():
                p=bin/name;p.write_text('#!'+sys.executable+'\n'+body);p.chmod(0o755)
            env={**os.environ,'XDG_RUNTIME_DIR':str(runtime),'PATH':str(bin)+os.pathsep+os.environ.get('PATH','')}
            for name in ('NOTIFY_SOCKET','WATCHDOG_PID','WATCHDOG_USEC'):env.pop(name,None)
            process=subprocess.Popen([sys.executable,'-m','waybridge','--config',str(config),'shot','serve'],cwd=Path(__file__).resolve().parents[1],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            def wait(predicate):
                deadline=time.monotonic()+6
                while time.monotonic()<deadline:
                    if process.poll() is not None:raise AssertionError(process.stderr.read().decode())
                    try:
                        value=predicate()
                        if value:return value
                    except (OSError,RuntimeError):pass
                    time.sleep(.03)
                raise AssertionError('queue recovery timed out')
            try:
                wait(lambda:endpoint.exists());rpc(endpoint,'shot')
                before=wait(lambda:(s if (s:=rpc(endpoint,'status'))['pending']==1 and s['bytes']>0 else None))
                endpoint.unlink()
                after=wait(lambda:(s if (s:=rpc(endpoint,'status'))['pending']==1 and s['bytes']==before['bytes'] else None))
                self.assertEqual(after['delivered'],0)
                gate.touch()
                done=wait(lambda:(s if (s:=rpc(endpoint,'status'))['pending']==0 and s['delivered']==1 else None))
                self.assertIsNone(done['last_error'])
            finally:
                gate.touch();process.terminate()
                try:process.wait(timeout=3)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
                process.stderr.close()
