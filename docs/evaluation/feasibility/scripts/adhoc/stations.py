import json, re, time, urllib.parse, urllib.request, urllib.error
BASE="https://www.onemap.gov.sg"; UA={"User-Agent":"CS5224-FlatSplit-feasibility/1.0"}
def search(q):
    url=BASE+"/api/common/elastic/search?"+urllib.parse.urlencode({"searchVal":q,"returnGeom":"Y","getAddrDetails":"Y"})
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=20) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e: return e.code, None
    except Exception as e: return None, None

print("="*80); print("C6 驗證：轉乘站的站碼表示方式"); print("="*80)
# Jurong East=EW24/NS1, Dhoby Ghaut=NS24/NE6/CC1, Bugis=EW12/DT14, Outram Park=EW16/NE3/TE17
for q in ["Jurong East MRT Station","Dhoby Ghaut MRT Station","Bugis MRT Station","Outram Park MRT Station"]:
    st,d = search(q)
    print(f"\n  ▸ {q}  (HTTP {st}, found={d.get('found') if d else '-'})")
    if d:
        for r in (d.get("results") or [])[:6]:
            sv=r.get("SEARCHVAL",""); codes=re.findall(r"\(([A-Z]{2}\d+(?:/[A-Z]{2}\d+)*)\)", sv)
            print(f"      {sv[:52]:52s} codes={codes}  lat={r.get('LATITUDE','')[:9]},{r.get('LONGITUDE','')[:10]}")
    time.sleep(1.2)

print()
print("="*80); print("C5 前置：HDB 鎮名能否查到參考座標（通勤起點）"); print("="*80)
for town in ["ANG MO KIO","TAMPINES","WOODLANDS","BUKIT BATOK","PUNGGOL"]:
    st,d = search(town)
    top=(d.get("results") or [{}])[0] if d else {}
    print(f"  {town:14s} HTTP {st} found={str(d.get('found') if d else '-'):5s} "
          f"top={str(top.get('SEARCHVAL'))[:34]:34s} {str(top.get('LATITUDE'))[:8]},{str(top.get('LONGITUDE'))[:9]}")
    time.sleep(1.2)

print()
print("="*80); print("地鐵站總量能否靠 search 列舉（themesvc 需 token 的替代方案）"); print("="*80)
st,d = search("MRT STATION")
print(f"  searchVal='MRT STATION' → HTTP {st} found={d.get('found') if d else '-'} "
      f"totalNumPages={d.get('totalNumPages') if d else '-'} (每頁 10 筆)")
if d: print(f"  → 若靠分頁列舉需 {d.get('totalNumPages')} 次請求，約 {d.get('totalNumPages',0)*1.0:.0f} 秒（1 req/s）")
