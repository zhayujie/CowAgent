#!/usr/bin/env bash
# Web Search using Bing China API (with pagination support)
# Usage: search.sh "query" [num_results]

set -euo pipefail

QUERY="${1:-}"
NUM_RESULTS="${2:-5}"

if [[ -z "$QUERY" ]]; then
    echo "Error: Please provide a search query"
    echo "Usage: $0 \"your search query\" [num_results]"
    exit 1
fi

# Validate num_results (supports up to 30)
if ! [[ "$NUM_RESULTS" =~ ^[0-9]+$ ]] || [ "$NUM_RESULTS" -lt 1 ] || [ "$NUM_RESULTS" -gt 30 ]; then
    echo "Error: num_results must be between 1 and 30"
    exit 1
fi

# URL encode the query
ENCODED_QUERY=$(python3 -c "import urllib.parse, sys; print(urllib.parse.quote(sys.argv[1]))" "$QUERY")

# Calculate pages needed (10 results per page)
PAGES=$(( (NUM_RESULTS + 9) / 10 ))

# Create temp file for responses
TMPFILE=$(mktemp /tmp/bing_search_XXXXXX.html)
trap "rm -f $TMPFILE" EXIT

# Fetch all pages
for ((page=0; page<PAGES; page++)); do
    FIRST=$((page * 10 + 1))
    
    if [ $page -eq 0 ]; then
        URL="https://cn.bing.com/search?q=${ENCODED_QUERY}"
    else
        URL="https://cn.bing.com/search?q=${ENCODED_QUERY}&first=${FIRST}"
    fi
    
    curl -s "$URL" \
        -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" \
        --max-time 15 >> "$TMPFILE" 2>/dev/null || true
    
    # Small delay to avoid rate limiting
    if [ $page -lt $((PAGES - 1)) ]; then
        sleep 0.5
    fi
done

# Check if we got any content
if [ ! -s "$TMPFILE" ]; then
    echo "Error: Failed to fetch search results. Please check your internet connection."
    exit 1
fi

# Parse results using Python
python3 - "$TMPFILE" "$NUM_RESULTS" "$QUERY" << 'PYTHON_EOF'
import sys
import re
import html

tmpfile = sys.argv[1]
num_results = int(sys.argv[2])
query = sys.argv[3]

with open(tmpfile, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# Extract search results
raw_results = re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', content, re.DOTALL)

if not raw_results:
    print(f"未找到与 '{query}' 相关的结果。")
    sys.exit(0)

# Parse and deduplicate results
seen_urls = set()
results = []

for r in raw_results:
    # Extract title from <h2> tag
    h2_match = re.search(r'<h2[^>]*>(.*?)</h2>', r, re.DOTALL)
    if h2_match:
        h2_content = h2_match.group(1)
        a_match = re.search(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', h2_content, re.DOTALL)
        if a_match:
            url = a_match.group(1)
            title_html = a_match.group(2)
            title = re.sub(r'<[^>]+>', '', title_html)
            title = html.unescape(title).strip()
        else:
            url = ''
            title = re.sub(r'<[^>]+>', '', h2_content)
            title = html.unescape(title).strip()
    else:
        url = ''
        title = '无标题'
    
    # Skip duplicates based on URL
    if url and url in seen_urls:
        continue
    if url:
        seen_urls.add(url)
    
    # Extract snippet from <p> tag
    snippet_match = re.search(r'<p[^>]*>(.*?)</p>', r, re.DOTALL)
    if snippet_match:
        snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1))
        snippet = html.unescape(snippet).strip()[:150]
    else:
        snippet = ''
    
    results.append((title, url, snippet))
    
    if len(results) >= num_results:
        break

if not results:
    print(f"未找到与 '{query}' 相关的结果。")
    sys.exit(0)

print(f"🔍 搜索 '{query}' 的结果 ({len(results)} 条):\n")

for i, (title, url, snippet) in enumerate(results, 1):
    print(f"{i}. **{title}**")
    print(f"   🔗 {url}")
    if snippet:
        print(f"   📄 {snippet}")
    print()

PYTHON_EOF
