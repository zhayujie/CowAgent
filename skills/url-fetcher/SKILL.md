---
name: url-fetcher
description: Fetch and extract content from web pages with anti-scraping bypass. Use when the user needs to access a URL, scrape web content, extract text from HTML pages, fetch API data, or bypass basic anti-bot protections. Supports HTML pages, JSON APIs, and common document formats with customizable headers, user agents, and extraction modes.
metadata:
  requires:
    bins: ["python3"]
  emoji: "🌐"
---

# URL Fetcher

Fetch and extract content from web pages with anti-scraping bypass capabilities.

## Features

- **Anti-scraping bypass**: Customizable user agents and headers
- **Multiple extraction modes**: Plain text, JSON data, Zhihu profile data
- **Flexible output**: Raw HTML, extracted text, or structured JSON
- **SSL control**: Optional SSL verification bypass
- **Cookie & Referer support**: Custom headers for authenticated access

## Usage

Run the fetch script with a URL:

```bash
scripts/fetch.py <url> [options]
```

**Parameters:**
- `url` (required): The URL to fetch
- `--ua`, `--user-agent`: User agent preset or custom string
  - Presets: `chrome`, `firefox`, `safari`, `mobile`, `bot`
  - Default: `chrome`
- `--timeout`: Request timeout in seconds (default: 30)
- `--header`, `-H`: Additional headers (format: `Key=Value`, can be used multiple times)
- `--no-verify`: Skip SSL certificate verification
- `--raw`: Output raw HTML/JSON content
- `--json`: Output as structured JSON
- `--extract`: Extraction mode: `text`, `json`, `zhihu`, `all` (default: `text`)
- `--cookie`: Cookie string for authenticated access
- `--referer`: Referer URL header

**Examples:**

```bash
# Basic fetch with text extraction
scripts/fetch.py "https://example.com"

# Use mobile user agent
scripts/fetch.py "https://example.com" --ua mobile

# Custom headers for API access
scripts/fetch.py "https://api.example.com/data" \
  -H "Authorization=Bearer token123" \
  -H "Accept=application/json"

# Fetch with cookie for authenticated content
scripts/fetch.py "https://example.com/profile" \
  --cookie "session_id=abc123; user=john"

# Extract JSON data from page
scripts/fetch.py "https://example.com" --extract json

# Output as JSON with all extraction modes
scripts/fetch.py "https://example.com" --json --extract all

# Bypass SSL verification (for self-signed certs)
scripts/fetch.py "https://internal-site.local" --no-verify

# Fetch Zhihu profile (may still get 403 due to strong anti-bot)
scripts/fetch.py "https://www.zhihu.com/people/username" --extract zhihu
```

## Extraction Modes

### text (default)
Extract readable text from HTML, removing scripts, styles, and tags. Returns:
- Page title
- Meta description
- Cleaned body text (truncated to 10,000 characters)

### json
Extract structured JSON data from HTML, including:
- JSON-LD structured data
- Initial state data (React/Vue/Nuxt)
- Embedded API responses

### zhihu
Extract Zhihu user profile data:
- Name, headline, description
- Gender, follower count
- Answer and article counts

### all
Run all extraction modes and combine results.

## Output Formats

### Text output (default)
Human-readable format with emojis and sections:
```
🌐 URL: https://example.com
📊 状态码: 200
📏 内容长度: 12345 字符

📄 标题: Example Page
📝 描述: Page description
📖 正文内容:
Extracted text content...
```

### JSON output (--json)
Structured JSON with metadata:
```json
{
  "status": 200,
  "url": "https://example.com",
  "extracted": "...",
  "json_data": {...},
  "zhihu_data": {...}
}
```

## Anti-Scraping Tips

1. **Rotate user agents**: Use different `--ua` presets for multiple requests
2. **Add delays**: Wait 1-2 seconds between requests to avoid rate limiting
3. **Use cookies**: Pass session cookies with `--cookie` for authenticated content
4. **Set referer**: Use `--referer` to appear as if coming from a legitimate source
5. **Bypass SSL**: Use `--no-verify` for sites with certificate issues

## Limitations

- **Strong anti-bot sites**: Some sites (like Zhihu) have advanced anti-scraping that may still block requests
- **JavaScript rendering**: This tool fetches static HTML only, no JavaScript execution
- **Rate limiting**: Aggressive fetching may trigger IP bans
- **Large pages**: Content is truncated to 10,000 characters in text mode

## Troubleshooting

**403 Forbidden:**
- Try different user agents: `--ua firefox` or `--ua bot`
- Add referer header: `--referer "https://google.com"`
- Use cookies if available: `--cookie "session=..."`

**SSL Certificate Error:**
- Use `--no-verify` to bypass SSL verification

**Timeout:**
- Increase timeout: `--timeout 60`

**Empty content:**
- Site may require JavaScript rendering (not supported)
- Check if content is loaded dynamically via API calls

## Dependencies

- Python 3.6+
- Standard library only (no external packages required)
