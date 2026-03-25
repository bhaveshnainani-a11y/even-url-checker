from http.server import BaseHTTPRequestHandler
import json
import httpx
import asyncio
import time
import os
import re

DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "urls-data.json")

with open(DATA_PATH) as f:
    URLS_DATA = json.load(f)

# Soft 404 detection patterns
SOFT_404_PATTERNS = [
    r'page\s*not\s*found',
    r'404\s*error',
    r'404\s*page',
    r'not\s*found',
    r'no\s*longer\s*available',
    r'does\s*not\s*exist',
    r'doesn.t\s*exist',
    r'page\s*doesn',
    r'oops.*wrong',
    r'nothing.*here',
    r'page.*missing',
    r'removed.*page',
    r'expired.*link',
]
SOFT_404_RE = re.compile('|'.join(SOFT_404_PATTERNS), re.IGNORECASE)


async def check_single_url(client, entry):
    url = entry["u"]
    start = time.time()
    result = {
        "checkUrl": url,
        "isActive": entry["a"],
        "totalAds": entry["t"],
        "activeAds": entry.get("ac", 0),
        "campaigns": entry.get("cs", []),
    }
    try:
        resp = await client.get(url, follow_redirects=True, timeout=15.0)
        elapsed = round((time.time() - start) * 1000)
        status_ok = 200 <= resp.status_code < 400

        # Soft 404 detection
        soft_404 = False
        if status_ok and resp.status_code == 200:
            body = resp.text[:5000].lower()
            title_match = re.search(r'<title>(.*?)</title>', body)
            title = title_match.group(1) if title_match else ''
            if SOFT_404_RE.search(title):
                soft_404 = True
            elif SOFT_404_RE.search(body) and len(resp.text) < 15000:
                soft_404 = True

        result.update({
            "status": resp.status_code,
            "ok": status_ok and not soft_404,
            "soft404": soft_404,
            "responseTime": elapsed,
            "finalUrl": str(resp.url),
            "redirected": str(resp.url) != url,
            "error": "Soft 404 - page shows not-found content" if soft_404 else None,
            "contentLength": len(resp.text),
        })
    except httpx.TimeoutException:
        result.update({"status": 0, "ok": False, "soft404": False, "responseTime": 15000,
                        "finalUrl": None, "redirected": False, "error": "Timeout (15s)", "contentLength": 0})
    except httpx.ConnectError as e:
        result.update({"status": 0, "ok": False, "soft404": False, "responseTime": 0,
                        "finalUrl": None, "redirected": False,
                        "error": "Connection failed: " + str(e)[:120], "contentLength": 0})
    except Exception as e:
        result.update({"status": 0, "ok": False, "soft404": False, "responseTime": 0,
                        "finalUrl": None, "redirected": False, "error": str(e)[:200], "contentLength": 0})
    return result


async def check_all():
    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0 (compatible; EvenURLChecker/1.0)"},
        verify=False,
    ) as client:
        sem = asyncio.Semaphore(10)
        async def limited(entry):
            async with sem:
                return await check_single_url(client, entry)
        tasks = [limited(e) for e in URLS_DATA]
        return await asyncio.gather(*tasks)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        results = asyncio.run(check_all())
        payload = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "totalChecked": len(results),
            "totalUp": sum(1 for r in results if r["ok"]),
            "totalDown": sum(1 for r in results if not r["ok"]),
            "totalSoft404": sum(1 for r in results if r.get("soft404")),
            "totalRedirected": sum(1 for r in results if r.get("redirected")),
            "activeDown": sum(1 for r in results if not r["ok"] and r["isActive"]),
            "results": results,
        }
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

