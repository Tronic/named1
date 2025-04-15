from datetime import datetime

from named1.dnserror import WontResolve

name = "RamCache"
cache_store = {}  # Global dictionary to store records


async def cache(qr):
    global cache_store
    name = qr["Question"][0]["name"]
    key = f"dns:{name}"
    if not qr.get("Answer"):
        return
    now = int(datetime.now().timestamp())
    old = cache_store.get(key, dict(Answer=[]))
    merger = {(t, data): expire for t, expire, data in old["Answer"]}
    for a in qr["Answer"]:
        n, t, expire, data = a["name"], a["type"], now + a["TTL"], a["data"]
        if n == name and merger.get((t, data), 0) < expire:
            merger[(t, data)] = expire
    answer = [[t, expire, data] for (t, data), expire in merger.items() if expire > now]
    if answer:
        expiry = min(now + 86400, max(merger.values()))
        cache_store[key] = {"Answer": answer, "Expiry": expiry}
    elif key in cache_store:
        del cache_store[key]
    # Remove from cache all expired keys
    for k in list(cache_store.keys()):
        if cache_store[k]["Expiry"] < now:
            del cache_store[k]


async def resolve_answer(name, type, recurse_cnames=True):
    global cache_store
    key = f"dns:{name}"
    now = int(datetime.now().timestamp())
    cached = cache_store.get(key)
    if not cached:
        raise WontResolve(f"[RamCache] {name} not found")
    try:
        answer = [
            dict(name=name, type=t, TTL=expire - now, data=data)
            for t, expire, data in cached["Answer"]
            if expire > now and (type == 255 or type == t or t == 5)
        ]
        if recurse_cnames:
            for cname in {a["data"] for a in answer if a["type"] == 5}:
                answer += await resolve_answer(cname, type, recurse_cnames=False)
    except Exception as e:
        raise WontResolve(
            f"[RamCache] Unexpected error responding from cached={cached!r}",
            exceptions=[e],
        )
    return answer


async def resolve(name, type, **kwargs):
    answer = await resolve_answer(name, type)
    if not answer:
        raise WontResolve("No suitable records found in cache")
    return {
        "Status": 0,
        "TC": False,
        "RD": True,
        "RA": True,
        "AD": False,
        "CD": False,
        "Question": [dict(name=name, type=type)],
        "Answer": answer,
        "NameClient": "RamCache",
    }
