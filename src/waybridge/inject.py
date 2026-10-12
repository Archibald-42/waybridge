"""Explicit evdev key emitter. No timing-based or autonomous typing."""
import os
import subprocess

PLAIN={}
for chars,codes in [('1234567890',range(2,12)),('qwertyuiop',range(16,26)),
                    ('asdfghjkl',range(30,39)),('zxcvbnm',range(44,51))]:
    PLAIN.update(zip(chars,codes))
PLAIN.update({'-':12,'=':13,'[':26,']':27,';':39,"'":40,'`':41,
              '\\':43,',':51,'.':52,'/':53,' ':57,'\n':28})
SHIFT=dict(zip('!@#$%^&*()_+{}:"~|<>?',
               [2,3,4,5,6,7,8,9,10,11,12,13,26,27,39,40,41,43,51,52,53]))

class Emitter:
    def __init__(self):
        self.env={**os.environ,'YDOTOOL_SOCKET':'/run/bridge-input/ydotool.sock'}
    def keys(self,events):
        subprocess.run(['ydotool','key','--key-delay','0',*events],env=self.env,check=True,
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=.5)
    def release(self):
        try:self.keys([f'{key}:0' for key in sorted(set(PLAIN.values())|set(SHIFT.values())|{14,42})])
        except (OSError,subprocess.SubprocessError):pass
    def emit(self,char):
        shifted=char in SHIFT or 'A'<=char<='Z'
        key=SHIFT[char] if char in SHIFT else PLAIN[char.lower()]
        sequence=(['42:1'] if shifted else [])+[f'{key}:1',f'{key}:0']+(['42:0'] if shifted else [])
        try:self.keys(sequence)
        except Exception:
            self.release();raise
