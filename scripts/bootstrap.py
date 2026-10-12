#!/usr/bin/env python3
"""Offline bootstrap: virtualenv + copied stdlib-only package, no system pip."""
import argparse
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import venv

p=argparse.ArgumentParser();p.add_argument('--prefix',default='.venv');args=p.parse_args()
source=Path(__file__).resolve().parents[1]/'src/waybridge'
prefix=Path(args.prefix).expanduser().resolve()
venv.EnvBuilder(with_pip=False).create(prefix)
python=prefix/'bin/python'
site=Path(subprocess.check_output([str(python),'-c','import sysconfig; print(sysconfig.get_path("purelib"))'],text=True).strip())
dest=site/'waybridge'
if dest.exists():shutil.rmtree(dest)
shutil.copytree(source,dest,ignore=shutil.ignore_patterns('__pycache__'))
entry=prefix/'bin/waybridge'
entry.write_text('#!/bin/sh\nexec '+shlex.quote(str(python))+' -m waybridge "$@"\n');entry.chmod(0o755)
print(entry)
