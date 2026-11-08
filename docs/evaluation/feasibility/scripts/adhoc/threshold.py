import time, urllib.parse, urllib.request, urllib.error
BASE="https://www.onemap.gov.sg"; UA={"User-Agent":"CS5224-FlatSplit-feasibility/1.0"}
def hit(q="Raffles Place"):
    url=BASE+"/api/common/elastic/search?"+urllib.parse.urlencode({"searchVal":q,"returnGeom":"Y","getAddrDetails":"Y"})
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=20) as r: return r.status
    except urllib.error.HTTPError as e: return e.code
    except Exception: return None

print("無 token 的 /common/elastic/search 速率門檻（每組 10 次請求）")
print(f"{'間隔':>8} {'200':>5} {'429':>5} {'實際速率':>12}  序列")
for gap in [0.25, 0.5, 1.0, 2.0, 3.0]:
    time.sleep(20)                      # 讓 bucket 回滿
    res=[]; t0=time.time()
    for i in range(10):
        res.append(hit())
        if i < 9: time.sleep(gap)
    el=time.time()-t0
    seq="".join("." if s==200 else ("X" if s==429 else "?") for s in res)
    print(f"{gap:>7.2f}s {res.count(200):>5} {res.count(429):>5} {10/el*60:>9.1f}/min  {seq}")
print()
print(". = 200 OK   X = 429 Too Many Requests")
