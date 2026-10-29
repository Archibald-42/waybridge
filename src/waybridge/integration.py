"""Backed-up, idempotent integration with Hyprland Lua/conf and Waybar JSONC."""
import json
from pathlib import Path
import shutil
import time
from .runtime import atomic

def backup(path):
    path=Path(path)
    if not path.exists():return
    root=Path.home()/'.local/state/waybridge/backups'/str(time.time_ns())
    try:relative=path.relative_to(Path.home())
    except ValueError:
        import hashlib
        relative=Path('external')/hashlib.sha256(str(path).encode()).hexdigest()[:16]/path.name
    dest=root/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,dest)

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

HYPR_MODULES=('hypr-client','hypr-server','hypr-helper','helper-start')

def hypr_record(config):
    return Path(config).parent/'hypr-integration.json'

def recorded_hypr(config):
    try:
        path=hypr_record(config)
        if path.stat().st_size>4096:return None
        value=json.loads(path.read_text())
        raw=value.get('path') if isinstance(value,dict) else None
        if isinstance(raw,str):
            result=Path(raw).expanduser()
            if result.is_absolute() and result.suffix in {'.lua','.conf'}:return result
    except (OSError,ValueError):pass
    return None

def hypr_candidates(config):
    home=Path.home()
    paths=[home/'.config/hypr/hyprland.lua',home/'.config/hypr/hyprland.conf']
    recorded=recorded_hypr(config)
    if recorded and recorded not in paths:paths.append(recorded)
    return paths

def hypr_reference(line,kind):
    """Match only our exact module includes, never arbitrary user source lines."""
    stripped=line.strip()
    import re
    if kind=='.lua':
        names='(?:'+'|'.join(re.escape(name) for name in HYPR_MODULES)+')'
        tail=r'/\.config/bridge/'+names+r'\.lua'
        quoted=r'["\'][^"\'\n]*'+tail+r'["\']'
        home=r'os\.getenv\(\s*["\']HOME["\']\s*\)\s*\.\.\s*["\']'+tail+r'["\']'
        return bool(re.fullmatch(r'dofile\s*\(\s*(?:'+quoted+'|'+home+r')\s*\)\s*;?\s*(?:--.*)?',stripped))
    match=re.fullmatch(r'source\s*=\s*(.+?)(?:\s+#.*)?',stripped)
    if not match:return False
    raw=match[1].strip().strip('"\'')
    return any(raw in {prefix+'/.config/bridge/'+name+'.conf' for prefix in ('~','$HOME',str(Path.home()))} for name in HYPR_MODULES)

def clean_hypr(text,kind):
    comments={'-- Waybridge session module','# Waybridge session module'}
    return ''.join(line for line in text.splitlines(keepends=True)
                   if line.strip() not in comments and not hypr_reference(line,kind))

def select_hypr_config(explicit=None,config=None):
    from .config import default_path
    config=Path(config or default_path())
    if explicit is not None:
        path=Path(explicit).expanduser().absolute()
        if path.suffix not in {'.lua','.conf'} or not path.is_file():
            raise ValueError('--hypr-config должен указывать на существующий .lua или .conf файл')
        return path
    recorded=recorded_hypr(config)
    if recorded and recorded.is_file():return recorded
    paths=[p for p in hypr_candidates(config) if p.is_file()]
    if len(paths)==1:return paths[0]
    if not paths:return None
    raise ValueError('Найдены hyprland.lua и hyprland.conf. Укажите активный файл: --hypr-config ПУТЬ')

def write_hypr(path,text):
    # Keep a dotfiles symlink in place; update its target with a backup.
    write(path.resolve(strict=True),text)

def unwire_hypr(config):
    for path in hypr_candidates(config):
        if not path.is_file():continue
        original=path.read_text();text=clean_hypr(original,path.suffix)
        if text!=original:write_hypr(path,text)

def wire_hypr(cfg,config,hypr_config=None):
    path=select_hypr_config(hypr_config,config)
    if path is None:
        print('Hyprland: основной конфиг не найден. Подключите hypr-'+cfg.role+'.lua через dofile или hypr-'+cfg.role+'.conf через source из ~/.config/bridge/.')
        return
    # Remove our includes from the previous format/role before selecting one.
    # Different paths can be aliases of one symlink target. Handle the selected
    # target exactly once and last so an old alias cannot undo its new include.
    paths=[p for p in hypr_candidates(config) if p.resolve()!=path.resolve()]+[path]
    for candidate in paths:
        if not candidate.is_file():continue
        original=candidate.read_text();text=clean_hypr(original,candidate.suffix)
        if candidate==path:
            module='hypr-'+cfg.role+path.suffix
            if text and not text.endswith('\n'):text+='\n'
            if path.suffix=='.lua':text+='-- Waybridge session module\ndofile(os.getenv("HOME") .. "/.config/bridge/'+module+'")\n'
            else:text+='# Waybridge session module\nsource = ~/.config/bridge/'+module+'\n'
        if text!=original:write_hypr(candidate,text)
    atomic(hypr_record(config),json.dumps({'path':str(path),'format':path.suffix[1:]}).encode())
    print('Hyprland: подключён '+module+' в '+str(path))

def wire(cfg,config,hypr_config=None):
    from .install import command
    home=Path.home()
    wire_hypr(cfg,config,hypr_config)
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
