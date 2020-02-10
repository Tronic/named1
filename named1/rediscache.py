import json
from datetime import datetime

import trio
from redio import Redis

from named1.dnserror import WontResolve

name = "RedisCache"

async def cache(qr):
    name = qr['Question'][0]['name']
    key = f"dns:{name}"
    if not qr.get('Answer'): return
    now = int(datetime.now().timestamp())
    redis = Redis()
    old = await redis.get(key).fulldecode
    r = old if isinstance(old, dict) else dict(Answer=[])
    merger = {(t, data): expire for t, expire, data in r['Answer']}
    for a in qr['Answer']:
        n, t, expire, data = a['name'], a['type'], now + a['TTL'], a['data']
        if n == name and merger.get((t, data), 0) < expire:
            merger[(t, data)] = expire
    answer = [[t, expire, data] for (t, data), expire in merger.items() if expire > now]
    if answer:
        r['Answer'] = answer
        # Cache up to longest TTL, max 1 day
        expiry = min(now + 86400, max(merger.values()))
        await redis.set(key, json.dumps(r)).expireat(key, expiry)
    elif old:
        await redis.delete(key)

async def resolve_answer(name, type, recurse_cnames=True):
    key = f"dns:{name}"
    now = int(datetime.now().timestamp())
    cached = await Redis().get(key).fulldecode
    if not cached: raise WontResolve(f"[RedisCache] {name} not found")
    try:
        answer = [
            dict(name=name, type=t, TTL = expire - now, data=data)
            for t, expire, data in cached['Answer'] if expire > now and (type == 255 or type == t or t == 5)
        ]
        if recurse_cnames:
            for cname in {a['data'] for a in answer if a['type'] == 5}:
                answer += await resolve_answer(cname, type, recurse_cnames=False)
    except Exception as e:
        raise WontResolve(f"[RedisCache] Unexpected error responding from cached={cached!r}", exceptions=[e])
    return answer

async def resolve(name, type, **kwargs):
    answer = await resolve_answer(name, type)
    if not answer: raise WontResolve("No suitable records found in cache")
    return {
        'Status': 0, 'TC': False, 'RD': True, 'RA': True, 'AD': False, 'CD': False,
        "Question": [dict(name=name, type=type)],
        "Answer": answer,
        'NameClient': 'RedisCache',
    }
