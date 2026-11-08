import json, time, urllib.parse, urllib.request, urllib.error

BASE="https://www.onemap.gov.sg"; UA={"User-Agent":"CS5224-FlatSplit-feasibility/1.0"}
def hit(q="Raffles Place"):
    url=BASE+"/api/common/elastic/search?"+urllib.parse.urlencode(
        {"searchVal":q,"returnGeom":"Y","getAddrDetails":"Y"})
    t0=time.perf_counter()
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=20) as r:
            return r.status, time.perf_counter()-t0, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, time.perf_counter()-t0, dict(e.headers)
    except Exception as e:
        return None, time.perf_counter()-t0, {}

print("### 階段 1：429 後的恢復時間（每 10 秒探測 1 次）")
t_start=time.time(); recovered=None
for i in range(1,19):
    st,dt,h=hit()
    el=time.time()-t_start
    ra=h.get("Retry-After") or h.get("retry-after")
    print(f"  +{el:5.0f}s  HTTP {st}  {dt*1000:5.0f}ms  Retry-After={ra}")
    if st==200:
        recovered=el; break
    time.sleep(10)
print(f"  → 恢復耗時 ≈ {recovered:.0f}s（自第一次探測起）" if recovered else "  → 180s 內未恢復")

print()
print("### 階段 2：突發容量 — 盡快連發，數到第一個 429 為止")
ok=0
for i in range(1,13):
    st,dt,h=hit()
    print(f"  req#{i:2d} HTTP {st} {dt*1000:5.0f}ms")
    if st==200: ok+=1
    else: break
print(f"  → 連發可成功 {ok} 次後被擋（bucket 容量 ≈ {ok}）")

print()
print("### 階段 3：恢復後測穩定速率 1 req / 5s")
time.sleep(60)
res=[]
for i in range(1,9):
    st,dt,h=hit(); res.append(st)
    print(f"  t={i*5:3d}s HTTP {st} {dt*1000:5.0f}ms")
    time.sleep(5)
n200=res.count(200)
print(f"  → 1 req/5s 共 8 次：200={n200}  429={res.count(429)}")
print(f"  → 推估無 token 可持續速率 ≈ {n200}/40s = {n200/40*60:.1f} req/min")
