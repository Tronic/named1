import json
from datetime import datetime

import trio
from trio_redis import Redis

from named1.dnserror import WontResolve

class Cacher:
    async def execute(self, task_status=trio.TASK_STATUS_IGNORED):
        async with Redis() as self.redis:
            self.lock = trio.Lock()
            task_status.started()
            await trio.sleep_forever()


    async def cache(self, qr):
        name = qr['Question'][0]['name']
        key = f"dns:{name}"
        if not qr.get('Answer'): return
        now = int(datetime.now().timestamp())
        async with self.lock:
            old = await self.redis.get(key)
            r = json.loads(old) if old else dict(Answer=[])
            merger = {(t, data): expire for t, expire, data in r['Answer']}
            for a in qr['Answer']:
                n, t, expire, data = a['name'], a['type'], now + a['TTL'], a['data']
                if n == name and merger.get((t, data), 0) < expire:
                    merger[(t, data)] = expire
            answer = [[t, expire, data] for (t, data), expire in merger.items() if expire > now]
            if not answer and old:
                await self.redis.delete(key)
            else:
                r['Answer'] = answer
                await self.redis.set(key, json.dumps(r))
                await self.redis.expireat(key, max(merger.values()))

    async def resolve_answer(self, name, type, recurse_cnames=True):
        key = f"dns:{name}"
        now = int(datetime.now().timestamp())
        async with self.lock:
            cached = await self.redis.get(key)
        if not cached: raise WontResolve(f"[RedisCache] {name} not found")
        try:
            cached = json.loads(cached)
            answer = [
                dict(name=name, type=t, TTL = expire - now, data=data)
                for t, expire, data in cached['Answer'] if expire > now and (type == 255 or type == t or t == 5)
            ]
            if recurse_cnames:
                for cname in {a['data'] for a in answer if a['type'] == 5}:
                    answer += await self.resolve_answer(cname, type, recurse_cnames=False)
        except Exception as e:
            raise WontResolve(f"[RedisCache] Unexpected error responding from cached={cached!r}", exceptions=[e])
        return answer

    async def resolve(self, name, type, **kwargs):
        answer = await self.resolve_answer(name, type)
        if not answer: raise WontResolve("No suitable records found in cache")
        return {
            'Status': 0, 'TC': False, 'RD': True, 'RA': True, 'AD': False, 'CD': False,
            "Question": [dict(name=name, type=type)],
            "Answer": answer,
            'Comment': 'Response from Named1 cache.',
            'NameClient': 'RedisCache',
        }
