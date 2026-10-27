#!/usr/bin/env python3
"""Reproducible source manifest and secret-free source archive."""
import argparse
import hashlib
import gzip
from pathlib import Path
import tarfile

root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--output',required=True);args=p.parse_args()
output=Path(args.output).resolve()
paths=[]
for top in ('src','scripts','tests','docs','.github'):
    paths += [x for x in (root/top).rglob('*') if x.is_file() and '__pycache__' not in x.parts]
paths += [root/x for x in ('setup.sh','README.md','SECURITY.md','LICENSE','pyproject.toml','.gitignore')]
paths=sorted(paths,key=lambda x:x.relative_to(root).as_posix())
manifest=''.join(hashlib.sha256(x.read_bytes()).hexdigest()+'  '+x.relative_to(root).as_posix()+'\n' for x in paths)
(root/'SHA256SUMS').write_text(manifest)
with output.open('wb') as destination, gzip.GzipFile(filename='',mode='wb',fileobj=destination,mtime=0) as compressed:
    with tarfile.open(fileobj=compressed,mode='w') as archive:
        for path in paths+[root/'SHA256SUMS']:
            info=archive.gettarinfo(str(path),'waybridge/'+path.relative_to(root).as_posix())
            info.uid=info.gid=0;info.uname=info.gname='';info.mtime=0
            info.mode=0o755 if path.stat().st_mode&0o111 else 0o644
            with path.open('rb') as f:archive.addfile(info,f)
print(output)
