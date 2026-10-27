"""One guided entry point for installation, peer replacement and role changes."""
import argparse
import json
import os
from pathlib import Path
import pwd
import shlex
import shutil
import subprocess
import tomllib
from .config import default_path,load
from .runtime import atomic
from .pairing import export,read,fingerprint,configuration
from .integration import backup,wire,shell_path,reload_panel

def run(args,timeout=None,check=True):return subprocess.run(args,check=check,timeout=timeout)
def choose(title,items,default=0):
    print('\n'+title)
    for index,item in enumerate(items,1):print(f'  {index}. {item}')
    while True:
        reply=input(f'Номер [{default+1}]: ').strip()
        if not reply:return default
        if reply.isdigit() and 1<=int(reply)<=len(items):return int(reply)-1
        print('Выберите номер из списка.')

def peers():
    data=json.loads(subprocess.check_output(['tailscale','status','--json'],text=True,timeout=5))
    result=[]
    for item in (data.get('Peer') or {}).values():
        ips=[x for x in item.get('TailscaleIPs',[]) if ':' not in x]
        if ips and item.get('Online'):result.append((item.get('HostName') or item.get('DNSName') or ips[0],ips[0]))
    return sorted(result)

def receive_profile(role,folder,own_ip=None):
    while True:
        files=[]
        for path in folder.glob('*.wbpair'):
            try:
                value=read(path)
                if value['role']!=role and value['ip']!=own_ip:files.append((path,value))
            except (OSError,ValueError):continue
        if files:
            files.sort(key=lambda item:item[0].stat().st_mtime,reverse=True)
            index=choose('Профиль второго компьютера:',[f'{p["hostname"]} · {p["ip"]} · {p["role"]} · {fingerprint(p)}' for _,p in files]+['Выбрать другой файл / получить Taildrop'])
            if index<len(files):return files[index]
        text=input('\nПеретащите сюда .wbpair второго ПК. Enter = получить Taildrop; q = закончить сейчас: ').strip()
        if text.lower()=='q':return None,None
        if not text:
            folder.mkdir(parents=True,exist_ok=True)
            print('Получаю Taildrop. Если файл ещё не отправлен, отправьте его на втором ПК и повторите Enter.')
            run(['sudo','tailscale','file','get','--conflict=rename',str(folder)],check=False)
        else:
            path=Path(text).expanduser()
            if not path.exists():
                parts=shlex.split(text)
                if len(parts)==1:path=Path(parts[0]).expanduser()
            try:
                value=read(path)
                if value['ip']==own_ip:raise ValueError('это профиль текущего ПК; выберите второй')
                if value['role']==role:raise ValueError('выбран профиль той же роли; нужен второй компьютер')
                return path,value
            except (OSError,ValueError) as e:print('Профиль не принят:',e)

def apply(own,peer,config,old,skip_root=False,integrate=True,start=True):
    from .install import root_plan,user_install,link
    from .control import execute
    previous=tomllib.loads(config.read_text()) if config.exists() else {}
    if skip_root and old and (old.role!=own['role'] or old.peer_ip!=peer['ip']):
        raise ValueError('--skip-root cannot change role or peer; update the system restriction too')
    if not skip_root:run(['sudo','-v'])
    # Stop workers before replacing their configuration.
    if old:
        try:execute(old,'stop')
        except (OSError,RuntimeError,subprocess.SubprocessError):
            run(['systemctl','--user','stop','bridge-key-code.service','bridge-shot-queue.service','bridge-files.service','bridge-note.service','bridge-shot-view.service'],check=False)
    data=configuration(own,peer,previous)
    payload=('\n'.join(k+' = '+json.dumps(v) for k,v in data.items())+'\n').encode()
    config.parent.mkdir(parents=True,exist_ok=True)
    import tempfile
    with tempfile.TemporaryDirectory(dir=config.parent) as td:
        candidate=Path(td)/'config.toml';atomic(candidate,payload);load(candidate)
    backup(config);atomic(config,payload)
    cfg=load(config);cfg.state.mkdir(parents=True,exist_ok=True);cfg.stopped.touch()
    folder=config.parent;auth=folder/'peer-auth.pub';host=folder/'peer-host.pub'
    atomic(auth,(peer['auth_key']+'\n').encode());atomic(host,(peer['host_key']+'\n').encode())
    atomic(folder/'peer.wbpair',(json.dumps(peer,indent=2)+'\n').encode())
    plan=folder/'system-plan.sh';root_plan(cfg,config,auth,plan)
    run(['bash','-n',str(plan)])
    if not skip_root:run(['sudo','bash',str(plan)])
    link(cfg,host);user_install(cfg,config);shell_path()
    if integrate:wire(cfg,config)
    run(['systemctl','--user','import-environment','WAYLAND_DISPLAY','HYPRLAND_INSTANCE_SIGNATURE','XDG_CURRENT_DESKTOP'],check=False)
    if shutil.which('hyprctl'):run(['hyprctl','reload'],check=False)
    reload_panel()
    if start and not skip_root:execute(cfg,'start')
    print('\n'+('Настройка завершена. Доступны снимки и файлы.' if not skip_root else 'User files installed; system plan NOT applied. Services remain stopped.'))
    print('Запуск / остановка в новом терминале: waybridge start / waybridge stop')
    print('Проверка соединения: waybridge check')
    return cfg

def update(cfg,config,integrate=True,start=True):
    """Refresh user components without changing keys, roles or system plans."""
    from .install import user_install
    from .control import execute
    was_running=not cfg.stopped.exists()
    execute(cfg,'stop')
    user_install(cfg,config);shell_path()
    if integrate:wire(cfg,config)
    run(['systemctl','--user','import-environment','WAYLAND_DISPLAY','HYPRLAND_INSTANCE_SIGNATURE','XDG_CURRENT_DESKTOP'],check=False)
    if shutil.which('hyprctl'):run(['hyprctl','reload'],check=False)
    if integrate:reload_panel()
    if start and was_running:execute(cfg,'start')
    print('Обновление завершено. Ключи и системные настройки сохранены.')
    print('Транспорт '+('запущен.' if start and was_running else 'остановлен; запуск: waybridge start'))
    return 0

def wizard(args):
    if os.geteuid()==0:raise RuntimeError('запускайте setup от обычного пользователя; sudo вызывается только для системных шагов')
    if not os.environ.get('XDG_RUNTIME_DIR'):raise RuntimeError('запустите setup в терминале своей графической сессии')
    config=Path(args.config or default_path()).expanduser().resolve();old=None
    if config.exists():old=load(config)
    if args.update:
        if not old:raise RuntimeError('Для обновления нужна существующая установка. Сначала выполните setup без --update.')
        if args.role or args.peer_profile or args.skip_root:raise ValueError('--update не меняет роли, профили или системные ограничения. Для смены ПК выполните обычный setup.')
        return update(old,config,not args.no_integrate,not args.no_start)
    if old:print(f'Сейчас: {old.role} · peer {old.peer_ip}. Можно заменить peer или выбрать другую роль.')
    role=args.role or ('client','server')[choose('Роль этого компьютера:',['Клиент — получает файлы, отправляет снимки','Сервер (ПК) — показывает снимки, отправляет файлы'],0 if not old or old.role=='client' else 1)]
    if not args.skip_packages:
        packages=['python','tailscale','openssh','nftables','inotify-tools']+(['acl','grim','waybar'] if role=='client' else ['imv','xdg-utils'])
        print('\nУстановка зависимостей через pacman. sudo нужен только для системной настройки.')
        run(['sudo','pacman','-S','--needed','--noconfirm',*packages])
    if not shutil.which('tailscale'):raise RuntimeError('установите tailscale и повторите setup')
    state=subprocess.run(['tailscale','status','--json'],capture_output=True,text=True)
    try:ready=state.returncode==0 and json.loads(state.stdout).get('BackendState')=='Running'
    except ValueError:ready=False
    if not ready:
        run(['sudo','systemctl','enable','--now','tailscaled.service'])
        print('Авторизуйте этот компьютер в своей сети Tailscale:')
        run(['sudo','tailscale','up'])
    if not Path('/etc/ssh/ssh_host_ed25519_key.pub').exists():run(['sudo','ssh-keygen','-A'])
    folder=Path.home()/'Downloads';folder.mkdir(parents=True,exist_ok=True)
    exported,own=export(role)
    if args.peer_profile:path=Path(args.peer_profile).expanduser();peer=read(path)
    else:
        targets=peers()
        if targets:
            index=choose('Отправить свой публичный профиль второму ПК через Taildrop:',['Пропустить — файл уже передан или передам вручную']+[name+' · '+ip for name,ip in targets],1)
            if index:
                run(['sudo','tailscale','file','cp',str(exported),targets[index-1][1]+':'],check=False)
        result=receive_profile(role,folder,own['ip']);path,peer=result
        if peer is None:
            print('Профиль готов. На втором ПК запустите тот же ./setup.sh; затем повторите здесь.')
            return 0
    configuration(own,peer)  # Reject same-role/self pairing before any configuration changes.
    print(f'\nВторой ПК: {peer["hostname"]} · {peer["ip"]} · {peer["user"]} · {peer["role"]}')
    print('Код сверки профиля:',fingerprint(peer))
    if not args.yes:input('Сверьте код с экраном второго ПК; Enter продолжает настройку, Ctrl+C отменяет: ')
    apply(own,peer,config,old,args.skip_root,not args.no_integrate,not args.no_start)
    return 0
