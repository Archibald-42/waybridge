#!/usr/bin/env python3
"""Deterministic unsigned Firefox bundle; signing is a separate AMO operation."""
import argparse
from pathlib import Path
import zipfile

root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--output',required=True);args=p.parse_args()
folder=root/'src/waybridge/browser/firefox'
with zipfile.ZipFile(args.output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(folder.iterdir()):
        if not path.is_file():continue
        info=zipfile.ZipInfo(path.name,date_time=(1980,1,1,0,0,0))
        info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16
        archive.writestr(info,path.read_bytes())
print(Path(args.output).resolve())
