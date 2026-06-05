#!/usr/bin/env python3
"""
URL Fetcher - Fetch and extract content from web pages with anti-scraping bypass.
Supports: HTML pages, JSON APIs, and common document formats.
"""

import sys
import json
import re
import argparse
import urllib.request
import urllib.error
import urllib.parse
import ssl
import gzip
import io

# Common User-Agent strings
USER_AGENTS = {
    "chrome": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "firefox": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "safari": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "mobile": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "bot": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
}

def create_ssl_context():
    """Create SSL context that doesn't verify certificates (for some sites)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

def fetch_url(url, user_agent="chrome", timeout=30, headers=None, no_verify=False):
    """Fetch URL content with customizable headers."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    req_headers = {
        "User-Agent": USER_AGENTS.get(user_agent, user_agent),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    }

    if headers:
        for h in headers:
            if "=" in h:
                key, val = h.split("=", 1)
                req_headers[key.strip()] = val.strip()

    req = urllib.request.Request(url, headers=req_headers)

    ssl_ctx = create_ssl_context() if no_verify else None

    try:
        if ssl_ctx:
            response = urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx)
        else:
            response = urllib.request.urlopen(req, timeout=timeout)

        data = response.read()
        encoding = response.headers.get("Content-Encoding", "")
        if encoding == "gzip":
            data = gzip.decompress(data)

        content_type = response.headers.get("Content-Type", "")
        charset = "utf-8"
        if "charset=" in content_type:
            charset = content_type.split("charset=")[-1].split(";")[0].strip()

        try:
            text = data.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            text = data.decode("utf-8", errors="replace")

        return {
            "status": response.status,
            "url": response.url,
            "content_type": content_type,
            "headers": dict(response.headers),
            "text": text,
        }
    except urllib.error.HTTPError as e:
        return {
            "status": e.code,
            "url": url,
            "error": f"HTTP {e.code}: {e.reason}",
            "text": "",
        }
    except urllib.error.URLError as e:
        return {
            "status": 0,
            "url": url,
            "error": f"URL Error: {e.reason}",
            "text": "",
        }
    except Exception as e:
        return {
            "status": 0,
            "url": url,
            "error": str(e),
            "text": "",
        }

def extract_readable_text(html):
    """Extract readable text from HTML, removing scripts, styles, and tags."""
    # Remove script and style blocks
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<noscript[^>]*>.*?</noscript>', '', html, flags=re.DOTALL | re.IGNORECASE)

    # Extract title
    title = ""
    title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
    if title_match:
        title = title_match.group(1).strip()

    # Extract meta description
    desc = ""
    desc_match = re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\'](.*?)["\']', html, re.IGNORECASE)
    if desc_match:
        desc = desc_match.group(1).strip()

    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', html)

    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&quot;', '"', text)
    text = re.sub(r'&#\d+;', '', text)
    text = text.strip()

    result = ""
    if title:
        result += f"📄 标题: {title}\n\n"
    if desc:
        result += f"📝 描述: {desc}\n\n"
    if text:
        # Truncate very long content
        if len(text) > 10000:
            text = text[:10000] + "\n\n... (内容已截断，共 {} 字符)".format(len(text) + 10000)
        result += f"📖 正文内容:\n{text}"

    return result

def extract_json_data(html):
    """Try to extract structured JSON data from HTML."""
    data = {}

    # Extract common JSON-LD
    jsonld = re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.DOTALL)
    if jsonld:
        try:
            data["json_ld"] = json.loads(jsonld[0])
        except json.JSONDecodeError:
            pass

    # Extract initial state/data patterns
    patterns = [
        (r'window\.__INITIAL_STATE__\s*=\s*({.*?});', "initial_state"),
        (r'window\.__NUXT__\s*=\s*({.*?});', "nuxt_data"),
        (r'"initialData"\s*:\s*({.*?})\s*[,}]', "initial_data"),
    ]
    for pattern, key in patterns:
        match = re.search(pattern, html, re.DOTALL)
        if match:
            try:
                data[key] = json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

    return data

def extract_zhihu_profile(html):
    """Extract Zhihu user profile data."""
    data = {}

    # Try to find user data in script tags
    patterns = [
        r'"name"\s*:\s*"([^"]*)"',
        r'"headline"\s*:\s*"([^"]*)"',
        r'"description"\s*:\s*"([^"]*)"',
        r'"gender"\s*:\s*(-?\d+)',
        r'"followerCount"\s*:\s*(\d+)',
        r'"answerCount"\s*:\s*(\d+)',
        r'"articlesCount"\s*:\s*(\d+)',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, html)
        if matches:
            key = pattern.split('"')[1]
            data[key] = matches[0]

    return data

def main():
    parser = argparse.ArgumentParser(description="Fetch and extract content from URLs")
    parser.add_argument("url", help="URL to fetch")
    parser.add_argument("--ua", "--user-agent", dest="user_agent", default="chrome",
                       help="User agent: chrome/firefox/safari/mobile/bot or custom string")
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout in seconds")
    parser.add_argument("--header", "-H", action="append", dest="headers",
                       help="Additional headers (format: Key=Value)")
    parser.add_argument("--no-verify", action="store_true", help="Skip SSL verification")
    parser.add_argument("--raw", action="store_true", help="Output raw HTML/JSON")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--extract", choices=["text", "json", "zhihu", "all"],
                       default="text", help="Extraction mode")
    parser.add_argument("--cookie", help="Cookie string")
    parser.add_argument("--referer", help="Referer URL")

    args = parser.parse_args()

    headers = args.headers or []
    if args.cookie:
        headers.append(f"Cookie={args.cookie}")
    if args.referer:
        headers.append(f"Referer={args.referer}")

    result = fetch_url(
        args.url,
        user_agent=args.user_agent,
        timeout=args.timeout,
        headers=headers,
        no_verify=args.no_verify,
    )

    if args.json:
        output = {
            "status": result["status"],
            "url": result.get("url", args.url),
        }
        if "error" in result:
            output["error"] = result["error"]
        if result.get("text"):
            if args.raw:
                output["content"] = result["text"]
            else:
                output["extracted"] = extract_readable_text(result["text"])
                if args.extract in ("json", "all"):
                    output["json_data"] = extract_json_data(result["text"])
                if args.extract in ("zhihu", "all"):
                    output["zhihu_data"] = extract_zhihu_profile(result["text"])
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"🌐 URL: {result.get('url', args.url)}")
        print(f"📊 状态码: {result['status']}")

        if "error" in result:
            print(f"❌ 错误: {result['error']}")
            sys.exit(1)

        if result.get("text"):
            if args.raw:
                print("\n--- 原始内容 ---")
                print(result["text"][:20000])
            else:
                print(f"📏 内容长度: {len(result['text'])} 字符")
                print()
                print(extract_readable_text(result["text"]))

                if args.extract in ("json", "all"):
                    json_data = extract_json_data(result["text"])
                    if json_data:
                        print("\n--- JSON 数据 ---")
                        print(json.dumps(json_data, ensure_ascii=False, indent=2)[:5000])

                if args.extract in ("zhihu", "all"):
                    zhihu_data = extract_zhihu_profile(result["text"])
                    if zhihu_data:
                        print("\n--- 知乎用户数据 ---")
                        for k, v in zhihu_data.items():
                            print(f"  {k}: {v}")

if __name__ == "__main__":
    main()
