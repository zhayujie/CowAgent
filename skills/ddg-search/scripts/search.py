#!/usr/bin/env python3
"""
DuckDuckGo Search Script
Supports web, images, news, and videos search.
Optional: --fetch to extract readable content from result URLs via url-fetcher skill.
"""

import sys
import os
import json
import argparse
import subprocess
from ddgs import DDGS

# Path to url-fetcher's fetch.py (sibling skill)
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FETCH_SCRIPT = os.path.join(SKILL_DIR, "..", "url-fetcher", "scripts", "fetch.py")


def search_web(query, max_results=5):
    """Search web pages"""
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=max_results))
    return results


def search_images(query, max_results=5):
    """Search images"""
    with DDGS() as ddgs:
        results = list(ddgs.images(query, max_results=max_results))
    return results


def search_news(query, max_results=5):
    """Search news articles"""
    with DDGS() as ddgs:
        results = list(ddgs.news(query, max_results=max_results))
    return results


def search_videos(query, max_results=5):
    """Search videos"""
    with DDGS() as ddgs:
        results = list(ddgs.videos(query, max_results=max_results))
    return results


def fetch_url_content(url, timeout=30):
    """Fetch and extract readable text from a URL using url-fetcher skill."""
    if not os.path.isfile(FETCH_SCRIPT):
        return {"error": f"url-fetcher skill not found at {FETCH_SCRIPT}"}
    try:
        result = subprocess.run(
            [sys.executable, FETCH_SCRIPT, url, "--json", "--timeout", str(timeout)],
            capture_output=True, text=True, timeout=timeout + 10
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
        else:
            return {"error": result.stderr.strip() or "fetch failed"}
    except subprocess.TimeoutExpired:
        return {"error": "fetch timed out"}
    except json.JSONDecodeError:
        return {"error": "invalid JSON response"}
    except Exception as e:
        return {"error": str(e)}


def main():
    parser = argparse.ArgumentParser(description='DuckDuckGo Search')
    parser.add_argument('query', help='Search query')
    parser.add_argument('--type', choices=['web', 'images', 'news', 'videos'],
                        default='web', help='Search type (default: web)')
    parser.add_argument('--max-results', type=int, default=5,
                        help='Maximum number of results (default: 5)')
    parser.add_argument('--json', action='store_true',
                        help='Output as JSON')
    parser.add_argument('--fetch', action='store_true',
                        help='Fetch and extract content from result URLs')
    parser.add_argument('--fetch-max', type=int, default=3,
                        help='Max URLs to fetch when --fetch is used (default: 3)')
    parser.add_argument('--fetch-timeout', type=int, default=30,
                        help='Timeout per URL fetch in seconds (default: 30)')

    args = parser.parse_args()

    try:
        if args.type == 'web':
            results = search_web(args.query, args.max_results)
        elif args.type == 'images':
            results = search_images(args.query, args.max_results)
        elif args.type == 'news':
            results = search_news(args.query, args.max_results)
        elif args.type == 'videos':
            results = search_videos(args.query, args.max_results)

        # Fetch content from result URLs if requested
        if args.fetch and results:
            fetch_count = min(args.fetch_max, len(results))
            for i in range(fetch_count):
                url = results[i].get('href', '')
                if url:
                    print(f"⏳ Fetching [{i+1}/{fetch_count}]: {url}", file=sys.stderr)
                    fetched = fetch_url_content(url, timeout=args.fetch_timeout)
                    results[i]['fetched'] = fetched

        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            for i, result in enumerate(results, 1):
                print(f"\n{'='*60}")
                print(f"[{i}] {result.get('title', 'No title')}")
                if 'href' in result:
                    print(f"    URL: {result['href']}")
                if 'body' in result:
                    print(f"    {result['body']}")
                if 'image' in result:
                    print(f"    Image: {result['image']}")
                if 'date' in result:
                    print(f"    Date: {result['date']}")

                # Show fetched content
                if 'fetched' in result:
                    fetched = result['fetched']
                    if 'error' in fetched:
                        print(f"    ⚠️  Fetch error: {fetched['error']}")
                    elif 'extracted' in fetched:
                        print(f"\n    --- Page Content ---")
                        # Indent the fetched content
                        lines = fetched['extracted'].split('\n')
                        for line in lines[:80]:  # Limit lines
                            print(f"    {line}")
                        if len(lines) > 80:
                            print(f"    ... (truncated, {len(lines)} lines total)")

            print(f"\n{'='*60}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
