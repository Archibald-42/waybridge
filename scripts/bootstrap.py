#!/usr/bin/env python3
"""Offline, immutable versioned installation; active workers retain their source."""
import argparse
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import venv

p=argparse.ArgumentParser();p.add_argument('--prefix',default='.venv');args=p.parse_args()
source=Path(__file__).resolve().parents[1]/'src/waybridge'
prefix=Path(args.prefix).expanduser().resolve()
python=prefix/'bin/python'
if not python.exists():venv.EnvBuilder(with_pip=False).create(prefix)
site=Path(subprocess.check_output([str(python),'-c','import sysconfig; print(sysconfig.get_path("purelib"))'],text=True).strip())
releases=site/'_waybridge_releases';releases.mkdir(parents=True,exist_ok=True)
release=Path(tempfile.mkdtemp(prefix='build-',dir=releases))
shutil.copytree(source,release/'waybridge',ignore=shutil.ignore_patterns('__pycache__'))
entry=prefix/'bin/waybridge'
pth=site/'waybridge-current.pth'
pth_new=pth.with_name('.waybridge-current-new')
pth_new.write_text('import os,sys; sys.path.insert(0, '+repr(str(release))+') if not os.environ.get(\"WAYBRIDGE_LAUNCHER_VERSION\") else None\n')
os.replace(pth_new,pth)
script='#!/bin/sh\nexport WAYBRIDGE_LAUNCHER_VERSION=1\nexport PYTHONPATH='+shlex.quote(str(release))+'\nexec '+shlex.quote(str(python))+' -m waybridge "$@"\n'
temporary=entry.with_name('.waybridge-new');temporary.write_text(script);temporary.chmod(0o755);os.replace(temporary,entry)
# A normal installation gets an easy command on the user's usual PATH.
if prefix==Path.home()/'.local/share/waybridge/venv':
    alias=Path.home()/'.local/bin/waybridge';alias.parent.mkdir(parents=True,exist_ok=True)
    temporary=alias.with_name('.waybridge-new');temporary.write_text('#!/bin/sh\nexec '+shlex.quote(str(entry))+' "$@"\n');temporary.chmod(0o755);os.replace(temporary,alias)
print(entry)
