from http.server import BaseHTTPRequestHandler
import json
import httpx
import asyncio
import time
from urllib.parse import urlparse

# Read embedded URL data
import os
DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "urls-data.json")

with open(DATA_PATH) as f:
    URLS_DATA = json.load(f)

async def check_single_url(client, entry):
    url = entry["checkUrl"]
    start = time.time()
    result = {
        "checkUrl": url,
        "isActive": entry["isActive"],
        "totalAds": entry["totalAds"],
        "variantCount": entry.get("variantCount", 0),
    }
    try:
        resp = await client.get(url, follow_redirects=True, timeout=15.0)
        elapsed = round((time.time() - start) * 1000)
        result.update({
            "status": resp.status_code,
            "ok": 200 <= resp.status_code < 400,
            "responseTime": elapsed,
            "finalUrl": str(resp.url),
            "redirected": str(resp.url) != url,
            "error": None,
        })
    except httpx.TimeoutException:
        result.update({"status": 0, "ok": False, "responseTime": 15000, "finalUrl": None, "redirected": False, "error": "Timeout (15s)"})
    except httpx.ConnectError as e:
        result.update({"status": 0, "ok": False, "responseTime": 0, "finalUrl": None, "redirected": False, "error": "Connection failed: " + str(e)[:100]})
    except Exception as e:
        result.update({"status": 0, "ok": False, "responseTime": 0, "finalUrl": None, "redirected": False, "error": str(e)[:200]})
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
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "totalChecked": len(results),
            "totalUp": sum(1 for r in results if r["ok"]),
            "totalDown": sum(1 for r in results if not r["ok"]),
            "results": results
        }).encode())
from http.server import BaseHTTPRequestHandler
import json
import httpx
import asyncio
import time
from urllib.parse import urlparse

# Read embedded URL data
import os
DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "urls-data.json")

with open(DATA_PATH) as f:
    URLS_DATA = json.load(f)

async def check_single_url(client, entry):
    url = entry["checkUrl"]
    start = time.time()
    result = {
        "checkUrl": url,
        "isActive": entry["isActive"],
        "totalAds": entry["totalAds"],
        "variantCount": entry.get("variantCount", 0),
    }
    try:
        resp = await client.get(url, follow_redirects=True, timeout=15.0)
        elapsed = round((time.time() - start) * 1000)
        result.update({
            "status": resp.status_code,
            "ok": 200 <= resp.status_code < 400,
            "responseTime": elapsed,
            "finalUrl": str(resp.url),
            "redirected": str(resp.url) != url,
            "error": None,
        })
    except httpx.TimeoutException:
        result.update({"status": 0, "ok": False, "responseTime": 15000, "finalUrl": None, "redirected": False, "error": "Timeout (15s)"})
    except httpx.ConnectError as e:
        result.update({"status": 0, "ok": False, "responseTime": 0, "finalUrl": None, "redirected": False, "error": f"Connection failed: {str(e)[:100]}"})
    except Exception as e:
        result.update({"status": 0, "ok": False, "responseTime": 0, "finalUrl": None, "redirected": False, "error": str(e)[:200]})
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
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "totalChecked": len(results),
            "totalUp": sum(1 for r in results if r["ok"]),
            "totalDown": sum(1 for r in results if not r["ok"]),
            "results": results
        }).encode())
