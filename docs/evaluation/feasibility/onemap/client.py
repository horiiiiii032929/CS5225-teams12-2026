"""OneMap API client — 只用標準函式庫，沒有外部相依。

設計依據全部來自 2026-10-11 的實測（見 README 的量測表），不是文件臆測：

- **併發 3**：序列呼叫路線端點 p50 約 860ms；併發拉到 20 時 p50 惡化到
  3,941ms、最大 7,327ms，而且開始出現 429。`docs/backend-design.md` 寫的
  「worker 最大併發 ≈3」是對的，這裡把它變成預設值。
- **250 calls/min**：官方上限是 300/min（SLA workshop slide 17，2025-10-01 起），
  這裡留 ~17% 餘裕。合約假設 C7 寫的 250 是改制前的舊數字。
- **自己做退避**：429 沒有 Retry-After header，兩種回應形狀（帶 token 是
  JSON、不帶是 HTML）都實測過。
- **token 效期 3 天不自動續期**：建構時就檢查 JWT 的 exp，剩不到 6 小時先警告，
  免得 worker 跑到一半整批失敗。
"""

import base64
import json
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .errors import (AuthError, Blocked, InvalidRequest, NoRouteFound,
                     OneMapError, RateLimited, TokenExpiring, UpstreamError)

BASE_URL = "https://www.onemap.gov.sg"

# 官方上限 300/min（2025-10-01 起，改制前 250）。預設留餘裕。
OFFICIAL_LIMIT_PER_MIN = 300
DEFAULT_LIMIT_PER_MIN = 250
DEFAULT_CONCURRENCY = 3

#: OneMap 的硬上限。實測 numItineraries=5 會回
#: 400 {"error": "numItineraries must be between 1 and 3 (inclusive)."}
MAX_ITINERARIES = 3


class _TokenBucket:
    """執行緒安全的權杖桶，把呼叫速率壓在 calls_per_min 以下。"""

    def __init__(self, calls_per_min):
        self.rate = calls_per_min / 60.0
        self.capacity = max(1.0, calls_per_min / 60.0)
        self._tokens = self.capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self):
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(self.capacity,
                                   self._tokens + (now - self._last) * self.rate)
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self.rate
            time.sleep(wait)


def decode_token(token):
    """不驗簽，只讀 JWT payload（我們要的是 exp，驗簽是伺服器的事）。"""
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part))
    except Exception as exc:
        raise OneMapError(f"無法解析 token：{exc}") from exc


class OneMapClient:
    """對 OneMap 的薄封裝，內建限流、退避重試與錯誤分類。

    用法：
        client = OneMapClient(token)
        places = client.search("kent ridge")
        stations = client.nearest_mrt(1.2966, 103.7764)
        route = client.route_pt("1.3691,103.8454", "1.2935,103.7846")
    """

    def __init__(self, token, *, calls_per_min=DEFAULT_LIMIT_PER_MIN,
                 max_attempts=3, timeout=40, warn_hours=6, user_agent=None,
                 recorder=None):
        if not token:
            raise AuthError("沒有提供 token。OneMap 除了 basemap/staticmap 之外"
                            "所有端點都需要 token（官方 workshop slide 7）。")
        self.token = token if token.lower().startswith("bearer ") else token
        self.max_attempts = max_attempts
        self.timeout = timeout
        self._bucket = _TokenBucket(calls_per_min)
        self._ua = user_agent or "CS5224-FlatSplit/1.0 (+github.com/horiiiiii032929)"
        #: 選用的 EvidenceRecorder。給它就會把每次 HTTP 往返原封不動存成 JSONL
        #: （Authorization header 會被遮蔽）。評估計畫 D-E5 要求保留原始數據。
        self.recorder = recorder
        self.stats = {"calls": 0, "retries": 0, "rate_limited": 0, "errors": 0}

        claims = decode_token(self.token)
        self.token_expires_at = claims.get("exp")
        self.token_user_id = claims.get("user_id")
        if self.token_expires_at:
            left = self.token_expires_at - time.time()
            if left <= 0:
                raise TokenExpiring(
                    "Token 已過期。OneMap token 效期 3 天且不會自動續期；"
                    "請重新呼叫 POST /api/auth/post/getToken。")
            self.token_hours_left = left / 3600.0
            if self.token_hours_left < warn_hours:
                import warnings
                warnings.warn(
                    f"OneMap token 只剩 {self.token_hours_left:.1f} 小時就到期。"
                    "長時間的快取填充作業請先換新 token。", stacklevel=2)
        else:
            self.token_hours_left = None

    # ---------------------------------------------------------------- 傳輸層

    def _classify(self, status, raw):
        """把 HTTP 狀態 + 回應內容對應到我們的錯誤型別。"""
        body = raw
        if isinstance(raw, (bytes, bytearray)):
            body = raw.decode("utf-8", "replace")
        parsed = None
        if isinstance(body, str):
            stripped = body.lstrip()
            if stripped.startswith("{") or stripped.startswith("["):
                try:
                    parsed = json.loads(body)
                except ValueError:
                    parsed = None
        msg = ""
        if isinstance(parsed, dict):
            msg = parsed.get("error") or parsed.get("message") or ""

        if status == 401:
            return AuthError(msg or "Unauthorized", status=status, body=body)
        if status == 403:
            return Blocked(msg or "被 WAF 擋下", status=status, body=body)
        if status == 429:
            # 帶 token 是 JSON、不帶是 HTML，兩種都在這裡收斂。
            return RateLimited(msg or "Too Many Requests", status=status, body=body)
        if status == 404 and "no route found" in msg.lower():
            return NoRouteFound(msg, status=status, body=body)
        if status and 400 <= status < 500:
            return InvalidRequest(msg or f"HTTP {status}", status=status, body=body)
        return UpstreamError(msg or f"HTTP {status}", status=status, body=body)

    def _backoff(self, attempt):
        """指數退避 + 抖動。OneMap 不給 Retry-After，所以排程得自己定。"""
        return min(8.0, 0.5 * (2 ** attempt)) * (0.5 + random.random())

    def _record(self, *, url, params, status, headers, body, elapsed,
                attempt, error=None):
        if self.recorder is None:
            return
        try:
            self.recorder.record(method="GET", url=url, params=params,
                                 status=status, headers=headers, body=body,
                                 elapsed=elapsed, attempt=attempt, error=error)
        except Exception:  # 記錄失敗不該害 worker 掛掉
            pass

    def _request(self, path, params):
        url = f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}"
        headers = {"User-Agent": self._ua, "Authorization": self.token}
        last = None
        for attempt in range(self.max_attempts):
            self._bucket.acquire()
            self.stats["calls"] += 1
            started = time.perf_counter()
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8", "replace")
                    elapsed = time.perf_counter() - started
                    self._record(url=url, params=params, status=resp.status,
                                 headers=dict(resp.headers), body=raw,
                                 elapsed=elapsed, attempt=attempt + 1)
                    return json.loads(raw), elapsed
            except urllib.error.HTTPError as exc:
                elapsed = time.perf_counter() - started
                raw = exc.read().decode("utf-8", "replace")
                self._record(url=url, params=params, status=exc.code,
                             headers=dict(exc.headers), body=raw,
                             elapsed=elapsed, attempt=attempt + 1)
                last = self._classify(exc.code, raw)
            except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                elapsed = time.perf_counter() - started
                self._record(url=url, params=params, status=None, headers={},
                             body=None, elapsed=elapsed, attempt=attempt + 1,
                             error=f"{type(exc).__name__}: {exc}")
                last = UpstreamError(f"{type(exc).__name__}: {exc}")

            if isinstance(last, RateLimited):
                self.stats["rate_limited"] += 1
            if not last.retryable or attempt == self.max_attempts - 1:
                break
            self.stats["retries"] += 1
            time.sleep(self._backoff(attempt))

        self.stats["errors"] += 1
        raise last

    # ------------------------------------------------------------------ 端點

    def search(self, query, *, page=1, raise_on_token_warning=False):
        """文字地理編碼。

        ⚠️ 這支端點目前處於「寬限期」：**即使 token 缺少/無效/過期，它還是會
        回傳資料**，只是多一個 `error` 欄位。實測三種狀態都照常回 10 筆。
        這代表不能靠「有拿到資料」判斷 token 是好的——要檢查 `error` 欄位，
        否則 token 默默失效時你不會發現，直到 SLA 收掉寬限期才整個爆掉。
        """
        payload, elapsed = self._request("/api/common/elastic/search", {
            "searchVal": query, "returnGeom": "Y", "getAddrDetails": "Y",
            "pageNum": page,
        })
        warning = payload.get("error")
        if warning and raise_on_token_warning:
            raise AuthError(warning, status=200, body=payload)
        return {
            "query": query,
            "found": payload.get("found", 0),
            "totalPages": payload.get("totalNumPages", 0),
            "results": payload.get("results") or [],
            "tokenWarning": warning,
            "elapsed": elapsed,
        }

    def nearest_mrt(self, lat, lon, radius_m=1000):
        """最近的地鐵站。radius_m 預設 2000、上限 5000（官方 slide 16）。

        回傳的是 `stations.dedupe_stations()` 收斂過的結果：每個實體車站一筆，
        附上它所有的路線代碼，並帶一個穩定的 `stationKey`。
        """
        from .stations import dedupe_stations
        payload, elapsed = self._request("/api/public/nearbysvc/getNearestMrtStops", {
            "latitude": lat, "longitude": lon,
            "radius_in_meters": min(int(radius_m), 5000),
        })
        entries = payload if isinstance(payload, list) else []
        return dedupe_stations(entries), elapsed

    def route_pt(self, start, end, *, date="10-13-2026", time_of_day="08:30:00",
                 max_walk_m=1000, itineraries=3):
        """公共運輸路線規劃。

        start/end 是 "lat,lon" 字串。date 是 MM-DD-YYYY（注意是美式順序）。

        成功回傳一個 dict，失敗丟 `NoRouteFound`（404）或 `InvalidRequest`（400）。
        呼叫端必須把 NoRouteFound 標記成 UNAVAILABLE，**絕不能當成 0 分鐘**
        （團隊決議 D06，也是 #19 的驗收條件）。

        ## 為什麼預設要 3 條而不是 1 條

        合約假設 C5 說通勤取「最短行程（shortest itinerary）」。早期版本用
        `numItineraries=1` 然後取 `itineraries[0]`，等於**假設** OneMap 會把
        最短的排第一——文件沒有保證這件事。

        現在改成要多條再自己挑 duration 最小的，並回報
        `upstreamFirstIsShortest`，讓「上游排序是否等於時間排序」變成量測結果
        而不是假設。多要 2 條不會多算 API 額度（仍是一次呼叫）。
        """
        # 實測：超過 3 會被擋下 ——
        # 400 {"error": "numItineraries must be between 1 and 3 (inclusive)."}
        itineraries = max(1, min(int(itineraries), MAX_ITINERARIES))
        payload, elapsed = self._request("/api/public/routingsvc/route", {
            "start": start, "end": end, "routeType": "pt",
            "date": date, "time": time_of_day, "mode": "TRANSIT",
            "maxWalkDistance": max_walk_m, "numItineraries": itineraries,
        })
        plan = payload.get("plan") or {}
        legs_out = []
        itins = plan.get("itineraries") or []
        if not itins:
            # 實測上 404 才是常態，但保險起見也擋 200+空陣列。
            raise NoRouteFound("回應成功但沒有任何 itinerary", status=200, body=payload)
        durations = [it["duration"] for it in itins]
        best = min(itins, key=lambda it: it["duration"])
        first_is_shortest = itins[0]["duration"] == best["duration"]
        for leg in best.get("legs") or []:
            legs_out.append({
                "mode": leg.get("mode"),
                "route": leg.get("route") or None,
                "seconds": leg.get("duration"),
                "from": (leg.get("from") or {}).get("name"),
                "to": (leg.get("to") or {}).get("name"),
            })
        return {
            "minutes": round(best["duration"] / 60.0, 1),
            "seconds": best["duration"],
            "itineraryCount": len(itins),
            "allDurationsSeconds": durations,
            "upstreamFirstIsShortest": first_is_shortest,
            "transfers": best.get("transfers"),
            "walkSeconds": best.get("walkTime"),
            "transitSeconds": best.get("transitTime"),
            "waitingSeconds": best.get("waitingTime"),
            "walkMetres": round(best.get("walkDistance") or 0, 1),
            "legs": legs_out,
            "elapsed": elapsed,
        }
