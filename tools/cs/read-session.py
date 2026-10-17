"""Inspect a CS-0.1 boundary log; keep only counts, PM4 hashes and first records.

Inputs/I/O content is not printed. PM4 hashes are per decoded frame, including
IB link headers, nested packets and zero padding, ending at XE_SWAP.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import struct

MAGIC = b'CS0LOG1\0'
HEADER = struct.Struct('<IIQQIIQ')
KINDS = ['invalid','timebase','system_time','uptime','input_result','input_state',
         'sync_request','sync_result','io_read','io_write','timer_fire','pm4_frame',
         'thread_start','signal','io_data','gpu_interrupt','gpu_fence','pm4_words']


def records(stream):
    if stream.read(8) != MAGIC:
        raise ValueError('invalid trace header')
    index = 0
    while raw := stream.read(HEADER.size):
        if len(raw) != HEADER.size:
            raise ValueError(f'truncated record at {index}')
        kind, thread, key, value, size, reserved, ns = HEADER.unpack(raw)
        if kind < 1 or kind >= len(KINDS) or reserved or size > 4096:
            raise ValueError(f'invalid record at {index}')
        payload = stream.read(size)
        if len(payload) != size:
            raise ValueError(f'truncated payload at {index}')
        yield {'index':index,'kind':KINDS[kind],'thread':f'{thread:08X}',
               'key':key,'value':value,'size':size,'host_ns':ns}
        index += 1


def inspect(path):
    kinds, threads = Counter(), Counter()
    frames, first = [], []
    total = 0
    first_ns = last_ns = None
    with path.open('rb') as f:
        for r in records(f):
            if first_ns is None:
                first_ns = r['host_ns']
            last_ns = r['host_ns']
            kinds[r['kind']] += 1
            threads[r['thread']] += 1
            if total < 40:
                first.append(r)
            if r['kind'] == 'pm4_frame':
                frames.append({'frame':r['key'],'hash':f"{r['value']:016X}",
                               'seconds':(r['host_ns'] - first_ns) / 1e9})
            total += 1
    return {'file':str(path),'bytes':path.stat().st_size,'records':total,
            'duration_seconds':(last_ns - first_ns) / 1e9 if total else 0,
            'kinds':dict(kinds),'threads':dict(threads),'first_records':first,'frames':frames}


def self_test():
    import io
    good = MAGIC + HEADER.pack(11, 7, 2, 123, 0, 0, 55)
    assert list(records(io.BytesIO(good)))[0]['kind'] == 'pm4_frame'
    for bad in (b'bad', good[:-1], MAGIC + HEADER.pack(1, 0, 0, 0, 4097, 0, 0)):
        try:
            list(records(io.BytesIO(bad)))
        except ValueError:
            pass
        else:
            raise AssertionError('malformed log accepted')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('trace', nargs='?', type=Path)
    p.add_argument('--output', type=Path)
    p.add_argument('--self-test', action='store_true')
    a = p.parse_args()
    self_test()
    if a.self_test:
        print('session reader self-test passed')
    else:
        if not a.trace:
            p.error('trace required')
        result = inspect(a.trace)
        if a.output:
            a.output.write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({k:v for k,v in result.items() if k not in ('first_records','frames')}, indent=2))
