"""Backed-up, idempotent integration with Hyprland Lua and Waybar JSONC."""
import json
from pathlib import Path
import shutil
import time
from .runtime import atomic

def backup(path):
    path=Path(path)
    if not path.exists():return
    root=Path.home()/'.local/state/waybridge/backups'/str(time.time_ns())
    dest=root/path.relative_to(Path.home());dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,dest)

def write(path,text):backup(path);atomic(path,text.encode())

def reload_panel():
    """Reload only this user's main Waybar, preserving unrelated panels."""
    import os,signal
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            if proc.stat().st_uid!=os.getuid():continue
            args=(proc/'cmdline').read_bytes().split(b'\0')
            if args[0] in (b'waybar',b'/usr/bin/waybar') and b'-c' not in args:os.kill(int(proc.name),signal.SIGUSR2)
        except (OSError,IndexError):pass

def jsonc(text):
    # Preserve URL/comment markers inside strings; support JSONC trailing commas.
    out=[];i=0;quoted=False;escaped=False
    while i<len(text):
        c=text[i]
        if quoted:
            out.append(c)
            if escaped:escaped=False
            elif c=='\\':escaped=True
            elif c=='"':quoted=False
            i+=1;continue
        if c=='"':quoted=True;out.append(c);i+=1;continue
        if text[i:i+2]=='//':
            end=text.find('\n',i);i=len(text) if end<0 else end;continue
        if text[i:i+2]=='/*':
            end=text.find('*/',i+2)
            if end<0:raise ValueError('unterminated JSONC comment')
            out.append(' ');i=end+2;continue
        if c==',':
            # Do trailing-comma removal after stripping comments.
            out.append(c)
        else:out.append(c)
        i+=1
    clean=''.join(out);out=[];quoted=False;escaped=False
    for i,c in enumerate(clean):
        if quoted:
            out.append(c)
            if escaped:escaped=False
            elif c=='\\':escaped=True
            elif c=='"':quoted=False
        elif c=='"':quoted=True;out.append(c)
        elif c==',' and clean[i+1:].lstrip().startswith(('}',']')):continue
        else:out.append(c)
    return json.loads(''.join(out))

def wire(cfg,config):
    from .install import command
    home=Path.home();module='hypr-client.lua' if cfg.role=='client' else 'hypr-server.lua'
    lua=home/'.config/hypr/hyprland.lua'
    if lua.exists():
        original=lua.read_text()
        text=''.join(line for line in original.splitlines(keepends=True)
                     if not ('dofile' in line and any(name in line for name in ('/.config/bridge/helper-start.lua','/.config/bridge/hypr-helper.lua'))))
        if module not in text:text+='\n-- Waybridge session module\ndofile(os.getenv("HOME") .. "/.config/bridge/'+module+'")\n'
        if text!=original:write(lua,text)
        print('Hyprland: модуль подключён.')
    else:print('Hyprland Lua config не найден; подключите ~/.config/bridge/'+module+' вручную.')
    waybar=home/'.config/waybar/config.jsonc'
    if not waybar.exists():waybar=home/'.config/waybar/config'
    if waybar.exists():
        try:
            data=jsonc(waybar.read_text())
            if not isinstance(data,(dict,list)):raise ValueError('Waybar object or list required')
            bars=data if isinstance(data,list) else [data]
            for bar in bars:
                if not isinstance(bar,dict):continue
                for field in ('modules-left','modules-center','modules-right'):
                    if field not in bar:continue
                    names=bar[field]
                    if not isinstance(names,list) or not all(isinstance(x,str) for x in names):raise ValueError('module list required')
                    bar[field]=[{'custom/bridge-clock':'clock'}.get(x,x) for x in names]
                    if cfg.role=='client':bar[field]=['custom/battery' if x=='battery' else x for x in bar[field]]
                    else:bar[field]=['battery' if x=='custom/battery' else x for x in bar[field]]
                bar.pop('custom/bridge-clock',None)
                bar.setdefault('clock',{'format':'{:%H:%M}'})
                if cfg.role=='client':
                    bar['custom/battery']={'exec':command(config,'battery'),'return-type':'json','restart-interval':3}
                else:
                    bar.pop('custom/battery',None)
                    bar.setdefault('battery',{'format':'{capacity}%'})
            write(waybar,json.dumps(data,ensure_ascii=False,indent=2)+'\n')
            print('Waybar: модули настроены; прежний конфиг сохранён в backups.')
        except ValueError:print('Waybar: сложный конфиг оставлен без изменения; добавьте модули вручную.')

def shell_path():
    """Install a backed-up user shell include; never shadow iproute2 intentionally."""
    import os,pwd
    home=Path.home();shell=Path(pwd.getpwuid(os.getuid()).pw_shell).name
    script=home/'.config/waybridge/path.sh'
    write(script,'# Waybridge user command directory\ncase ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$PATH:$HOME/.local/bin" ;; esac\n')
    if shell=='fish':
        write(home/'.config/fish/conf.d/waybridge.fish','if not contains -- "$HOME/.local/bin" $PATH\n    set -gx PATH $PATH "$HOME/.local/bin"\nend\n')
    elif shell=='zsh':
        for name in ('.zshrc','.zprofile'):
            path=home/name;text=path.read_text() if path.exists() else ''
            if '/.config/waybridge/path.sh' not in text:write(path,text+'\n. "$HOME/.config/waybridge/path.sh"\n')
    else:
        for name in ('.bashrc','.profile'):
            path=home/name;text=path.read_text() if path.exists() else ''
            if '/.config/waybridge/path.sh' not in text:write(path,text+'\n. "$HOME/.config/waybridge/path.sh"\n')
        login=home/'.bash_profile'
        if login.exists():
            text=login.read_text()
            if '/.config/waybridge/path.sh' not in text:write(login,text+'\n. "$HOME/.config/waybridge/path.sh"\n')
    print('Shell: путь настроен. Откройте новый терминал для команды waybridge.')
