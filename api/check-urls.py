from http.server import BaseHTTPRequestHandler
import json
import httpx
import asyncio
import time
import os
import re
from urllib.parse import urlparse

DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "urls-data.json")

with open(DATA_PATH) as f:
    URLS_DATA = json.load(f)

# Soft 404 detection patterns — title/H1 patterns (high confidence)
TITLE_404_PATTERNS = [
    r'page\s*not\s*found',
    r'404\s*error',
    r'404\s*page',
    r'error\s*404',
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
    r'something\s*went\s*wrong',
    r'we\s*couldn.t\s*find',
    r'can.t\s*find\s*(this|that|the)\s*page',
    r'under\s*(maintenance|construction)',
    r'temporarily\s*unavailable',
    r'coming\s*soon',
    r'site\s*(is\s*)?down',
    r'access\s*denied',
    r'forbidden',
    r'url\s*(is\s*)?(not\s*valid|invalid)',
    r'no\s*results?\s*found',
    r'this\s*page\s*(isn.t|is\s*not)\s*available',
    r'sorry.*problem',
    r'service\s*unavailable',
    r'internal\s*server\s*error',
    r'bad\s*gateway',
]
TITLE_404_RE = re.compile('|'.join(TITLE_404_PATTERNS), re.IGNORECASE)

# Body patterns — checked in first 10KB (broader net)
BODY_404_PATTERNS = TITLE_404_PATTERNS + [
    r'<h1[^>]*>.*?(not\s*found|404|error|oops|sorry).*?</h1>',
    r'<h2[^>]*>.*?(not\s*found|404|error|oops|sorry).*?</h2>',
    r'class=["\'][^"\']*\b(error|not-found|notfound|page-404)\b',
    r'id=["\'][^"\']*\b(error|not-found|notfound|page-404)\b',
]
BODY_404_RE = re.compile('|'.join(BODY_404_PATTERNS), re.IGNORECASE)

# Minimum meaningful content length (chars of visible text)
MIN_CONTENT_LENGTH = 500


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
        final_url = str(resp.url)
        redirected = final_url != url

        # --- Comprehensive soft 404 detection ---
        soft_404 = False
        soft_reason = None

        if status_ok and resp.status_code == 200:
            body_raw = resp.text
            body = body_raw[:10000].lower()
            visible = None

            # 1. Title check (high confidence)
            title_match = re.search(r'<title>(.*?)</title>', body)
            title = title_match.group(1).strip() if title_match else ''
            if TITLE_404_RE.search(title):
                soft_404 = True
                soft_reason = f"Title contains error text: '{title[:80]}'"

            # 2. H1 check (high confidence)
            if not soft_404:
                h1_matches = re.findall(r'<h1[^>]*>(.*?)</h1>', body, re.DOTALL)
                for h1 in h1_matches:
                    h1_text = re.sub(r'<[^>]+>', '', h1).strip()
                    if TITLE_404_RE.search(h1_text):
                        soft_404 = True
                        soft_reason = f"H1 contains error text: '{h1_text[:80]}'"
                        break

            # 3. Body content check (broader, no size limit)
            if not soft_404 and BODY_404_RE.search(body):
                soft_404 = True
                soft_reason = "Body contains error/not-found patterns"

            # 4. Thin content detection — strip HTML tags and check visible text
            if not soft_404:
                visible = re.sub(r'<script[^>]*>.*?</script>', '', body_raw[:20000], flags=re.DOTALL | re.IGNORECASE)
                visible = re.sub(r'<style[^>]*>.*?</style>', '', visible, flags=re.DOTALL | re.IGNORECASE)
                visible = re.sub(r'<[^>]+>', ' ', visible)
                visible = re.sub(r'\s+', ' ', visible).strip()
                if len(visible) < MIN_CONTENT_LENGTH:
                    soft_404 = True
                    soft_reason = f"Thin content: only {len(visible)} chars of visible text"

            # 5. Redirect-to-homepage detection
            if not soft_404 and redirected:
                orig_parsed = urlparse(url)
                final_parsed = urlparse(final_url)
                orig_path = orig_parsed.path.rstrip('/')
                final_path = final_parsed.path.rstrip('/')
                if orig_path and not final_path:
                    soft_404 = True
                    soft_reason = f"Redirected to homepage: {final_url}"

            # 6. Meta noindex check (often used on error pages)
            if not soft_404:
                noindex = re.search(r'<meta[^>]*name=["\']robots["\'][^>]*content=["\'][^"\']*noindex', body)
                if noindex and (len(visible) if visible else len(body_raw)) < 5000:
                    soft_404 = True
                    soft_reason = "Page has noindex meta + thin content"

        # Non-200 success codes that are suspicious
        if status_ok and resp.status_code in (204, 202) and not soft_404:
            soft_404 = True
            soft_reason = f"Suspicious status code {resp.status_code} for a landing page"

        error_msg = None
        if soft_404:
            error_msg = f"Soft 404 - {soft_reason}"
        elif not status_ok:
            error_msg = f"HTTP {resp.status_code}"

        result.update({
            "status": resp.status_code,
            "ok": status_ok and not soft_404,
            "soft404": soft_404,
            "soft404Reason": soft_reason,
            "responseTime": elapsed,
            "finalUrl": final_url,
            "redirected": redirected,
            "error": error_msg,
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
