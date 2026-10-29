"""Versioned screenshot frame and verified acknowledgement."""
import hashlib
import json
import re
import struct
import zlib
from .runtime import decode_json

LIMIT=32*1024*1024
MAGIC=b'WB1 '

def validate_png(data):
    if not data.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('invalid PNG signature')
    offset=8;first=True;seen_data=False
    while offset+12<=len(data):
        size=struct.unpack('>I',data[offset:offset+4])[0];end=offset+12+size
        if end>len(data):raise ValueError('truncated PNG')
        kind=data[offset+4:offset+8];payload=data[offset+8:offset+8+size]
        crc=struct.unpack('>I',data[offset+8+size:end])[0]
        if zlib.crc32(kind+payload)&0xffffffff!=crc:raise ValueError('PNG CRC mismatch')
        if first:
            if kind!=b'IHDR' or size!=13:raise ValueError('missing IHDR')
            width,height=struct.unpack('>II',payload[:8])
            if not (0<width<=16384 and 0<height<=16384 and width*height<=40000000):raise ValueError('image dimensions too large')
        first=False;seen_data|=kind==b'IDAT'
        if kind==b'IEND':
            if size or end!=len(data) or not seen_data:raise ValueError('invalid IEND')
            return
        offset=end
    raise ValueError('missing IEND')

def frame(identifier,data,magic=MAGIC):
    if not re.fullmatch('[a-f0-9]{32}',identifier) or not 0<len(data)<=LIMIT:raise ValueError('invalid frame')
    digest=hashlib.sha256(data).hexdigest()
    header={'id':identifier,'sha256':digest,'size':len(data)}
    return magic+json.dumps(header,separators=(',',':')).encode()+b'\n'+data,header

def parse(stream,first=None,*,magic=MAGIC,validator=validate_png):
    if first is None:first=stream.read(4)
    if first!=magic:
        data=first+stream.read(LIMIT+1)
        if len(data)>LIMIT:raise ValueError('legacy PNG too large')
        validate_png(data)
        return None,data
    line=stream.readline(1025)
    if len(line)>1024 or not line.endswith(b'\n'):raise ValueError('header too long')
    header=decode_json(line)
    if not isinstance(header,dict) or set(header)!={'id','sha256','size'}:raise ValueError('header fields must be id, sha256, size')
    if not isinstance(header.get('id'),str) or not isinstance(header.get('sha256'),str):raise ValueError('id and hash must be strings')
    if not re.fullmatch('[a-f0-9]{32}',header.get('id','')):raise ValueError('bad job id')
    if not re.fullmatch('[a-f0-9]{64}',header.get('sha256','')):raise ValueError('bad hash')
    size=header.get('size')
    if not isinstance(size,int) or isinstance(size,bool) or not 0<size<=LIMIT:raise ValueError('bad size')
    data=stream.read(size)
    if len(data)!=size or stream.read(1):raise ValueError('body size mismatch')
    if hashlib.sha256(data).hexdigest()!=header['sha256']:raise ValueError('body hash mismatch')
    validator(data)
    return header,data

def verify_ack(data,header):
    try:ack=decode_json(data)
    except (ValueError,UnicodeError):return False
    return isinstance(ack,dict) and ack.get('ok') is True and all(ack.get(k)==header[k] for k in ('id','sha256','size'))
