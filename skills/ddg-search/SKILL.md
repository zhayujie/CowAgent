---
name: ddg-search
description: Search the web using DuckDuckGo. Use when the user asks to search for information, find web pages, look up news, search images or videos, or needs to research a topic online. Triggers on keywords like "search", "find", "look up", "Google", "search engine", or any request to find information on the internet.
metadata:
  requires:
    bins: ["python3"]
---

# DuckDuckGo Search

Free web search via DuckDuckGo — no API key required.

## Setup

Install the Python package (one-time):

```bash
pip install ddgs
```

## Usage

Run the search script:

```bash
python <base_dir>/scripts/search.py "<query>" [options]
```

### Options

- `--type`: Search type — `web` (default), `images`, `news`, `videos`
- `--max-results`: Number of results (default: 5)
- `--json`: Output as JSON
- `--fetch`: Fetch and extract readable content from result URLs (requires `url-fetcher` skill)
- `--fetch-max`: Max URLs to fetch when `--fetch` is used (default: 3)
- `--fetch-timeout`: Timeout per URL fetch in seconds (default: 30)

### Examples

**Basic web search:**
```bash
python <base_dir>/scripts/search.py "Python tutorial"
```

**Search news:**
```bash
python <base_dir>/scripts/search.py "AI breakthroughs" --type news --max-results 10
```

**Search images (JSON output):**
```bash
python <base_dir>/scripts/search.py "cute cats" --type images --json
```

**Chinese search:**
```bash
python <base_dir>/scripts/search.py "大语言模型" --max-results 5
```

**Search and fetch page content:**
```bash
python <base_dir>/scripts/search.py "深惠城际 开通时间" --fetch --fetch-max 2
```
This will search, then automatically fetch and extract readable text from the first 2 result URLs.

## Rate Limiting

DuckDuckGo may rate-limit high-frequency requests (returns 403 or captcha). If this happens:
- Wait a few seconds before retrying
- Reduce `--max-results`
- Use a proxy if needed

## Output Format

**Text output** (default): Title, URL, and snippet for each result.

**JSON output** (`--json`): Array of result objects with fields like `title`, `href`, `body`, `image`, `date` depending on search type.
