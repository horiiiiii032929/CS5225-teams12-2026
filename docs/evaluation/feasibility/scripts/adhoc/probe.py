import json, time, urllib.parse, urllib.request, statistics, sys

BASE = "https://www.onemap.gov.sg"
UA = {"User-Agent": "CS5224-FlatSplit-feasibility/1.0"}

def get(path, params=None, token=None, timeout=20):
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    h = dict(UA)
    if token: h["Authorization"] = token
    req = urllib.request.Request(url, headers=h)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            dt = time.perf_counter() - t0
            try: parsed = json.loads(body)
            except Exception: parsed = body[:300]
            return r.status, parsed, dt, dict(r.headers)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        dt = time.perf_counter() - t0
        try: parsed = json.loads(body)
        except Exception: parsed = body[:300]
        return e.code, parsed, dt, dict(e.headers)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}", time.perf_counter()-t0, {}

def search(q, token=None):
    return get("/api/common/elastic/search",
               {"searchVal": q, "returnGeom": "Y", "getAddrDetails": "Y"}, token)

print("="*78)
print("A. SEARCH 無 token — 樣本目的地（C4 驗證）")
print("="*78)
samples = ["NUS", "Raffles Place", "Changi Business Park", "one-north",
           "Jurong East MRT", "Tokyo Tower", "Marina Bay Financial Centre",
           "NTU", "Tampines Hub", "117510"]
lat = []
for q in samples:
    st, d, dt, _ = search(q)
    if isinstance(d, dict):
        n = len(d.get("results") or [])
        first = (d.get("results") or [{}])[0]
        err = d.get("error")
        print(f"  {q:30s} HTTP {st} {dt*1000:6.0f}ms found={str(d.get('found')):5s} n={n:2d} "
              f"top={str(first.get('SEARCHVAL'))[:28]:28s} err={'YES' if err else 'no'}")
        lat.append(dt)
    else:
        print(f"  {q:30s} HTTP {st} -> {d}")
    time.sleep(0.25)

print()
print("="*78)
print("B. 無 token 的 error 欄位全文")
print("="*78)
st, d, dt, hdrs = search("Raffles Place")
print("  HTTP", st, "| error =", json.dumps(d.get("error"), ensure_ascii=False) if isinstance(d,dict) else d)
print("  回應 top-level keys:", list(d.keys()) if isinstance(d,dict) else "-")

print()
print("="*78)
print("C. 錯誤/邊界輸入的回應形狀（#14 需要明確狀態）")
print("="*78)
edge = {"空字串": "", "單字元": "a", "兩字元": "ab", "亂碼": "zzzqqqxxx999",
        "非新加坡": "Eiffel Tower", "SQL注入樣": "'; DROP TABLE--", "中文": "新加坡國立大學",
        "超長(150字)": "a"*150}
for name, q in edge.items():
    st, d, dt, _ = search(q)
    if isinstance(d, dict):
        print(f"  {name:14s} HTTP {st} found={str(d.get('found')):5s} n={len(d.get('results') or []):2d} "
              f"keys={[k for k in d.keys() if k!='results']} top={str((d.get('results') or [{}])[0].get('SEARCHVAL'))[:25]}")
    else:
        print(f"  {name:14s} HTTP {st} -> {str(d)[:120]}")
    time.sleep(0.25)

print()
print("="*78)
print("D. ROUTING / 其他需 token 端點 的失敗回應（存取阻塞證據）")
print("="*78)
endpoints = [
 ("PT 路線規劃", "/api/public/routingsvc/route",
  {"start":"1.3203,103.7846","end":"1.2966,103.7764","routeType":"pt",
   "date":"10-13-2026","time":"08:30:00","mode":"TRANSIT",
   "maxWalkDistance":"1000","numItineraries":"1"}),
 ("步行路線",   "/api/public/routingsvc/route",
  {"start":"1.3203,103.7846","end":"1.2966,103.7764","routeType":"walk"}),
 ("主題圖資(地鐵站)", "/api/public/themesvc/retrieveTheme", {"queryName":"train_station"}),
 ("主題圖資清單", "/api/public/themesvc/getAllThemesInfo", {"moreInfo":"Y"}),
 ("反向地理編碼", "/api/public/revgeocode", {"location":"1.3203,103.7846","buffer":"50","addressType":"All"}),
 ("行政區查詢", "/api/public/popapi/getPlanningareaNames", {"year":"2019"}),
]
for name, path, params in endpoints:
    st, d, dt, hdrs = get(path, params)
    print(f"  {name:18s} HTTP {st:>4} {dt*1000:6.0f}ms -> {json.dumps(d, ensure_ascii=False)[:150] if isinstance(d,(dict,list)) else str(d)[:150]}")
    time.sleep(0.25)

print()
print("="*78)
print("E. 取 token 端點是否存在（需帳密，這裡只驗端點與錯誤形狀）")
print("="*78)
for path in ["/api/auth/post/getToken"]:
    req = urllib.request.Request(BASE+path, data=json.dumps({"email":"probe@example.invalid","password":"x"}).encode(),
                                 headers={**UA, "Content-Type":"application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print(f"  POST {path} HTTP {r.status} -> {r.read()[:200]}")
    except urllib.error.HTTPError as e:
        print(f"  POST {path} HTTP {e.code} -> {e.read().decode('utf-8','replace')[:200]}")
    except Exception as e:
        print(f"  POST {path} ERR {type(e).__name__}: {e}")

print()
print("="*78)
print(f"F. SEARCH 延遲統計（n={len(lat)}，上面 A 段的樣本）")
print("="*78)
if lat:
    s = sorted(lat)
    print(f"  min={s[0]*1000:.0f}ms  p50={statistics.median(s)*1000:.0f}ms  "
          f"p95={s[int(len(s)*0.95)-1]*1000:.0f}ms  max={s[-1]*1000:.0f}ms")
