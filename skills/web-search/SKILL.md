---
name: web-search
description: Search the web using Bing China (cn.bing.com). Use when the user asks to search for information, find articles, look up topics, or needs current web content. Supports general web search with title, URL, and snippet extraction.
metadata:
  requires:
    bins: ["curl", "python3"]
---

# Web Search

Search the web using Bing China API. This skill provides reliable web search functionality from mainland China without requiring API keys.

## Features

- **Bing China Search**: Uses cn.bing.com which is accessible from mainland China
- **Structured Results**: Returns title, URL, and snippet for each result
- **Configurable**: Adjust number of results (default: 5, max: 10)
- **No API Key Required**: Works out of the box

## Usage

Run the search script with a query:

```bash
scripts/search.sh "your search query" [num_results]
```

**Parameters:**
- `query` (required): The search terms
- `num_results` (optional): Number of results to return (default: 5, max: 30)

**Examples:**

```bash
# Basic search
scripts/search.sh "Linux tutorial"

# Get 8 results
scripts/search.sh "Python best practices" 8
```

**Output Format:**

```
🔍 Search results for 'Linux tutorial' (5 results):

1. Linux Tutorial - W3Schools
   🔗 https://www.w3schools.com/linux/
   📄 Linux is a family of open-source Unix-like operating systems...

2. Linux.org
   🔗 https://www.linux.org/
   📄 The Linux Foundation supports the creation of innovative...
```

## Implementation Details

The script uses `curl` to fetch Bing China search results and `python3` to parse the HTML response. It supports **pagination** to fetch up to 30 results by automatically requesting multiple pages.

Features:
- **Pagination**: Automatically fetches multiple pages when more than 10 results are requested
- **Deduplication**: Removes duplicate results based on URL
- **Structured output**: Extracts titles, URLs, and text snippets (up to 150 characters)

Results are sorted by relevance as returned by Bing.

## Troubleshooting

**No results found:**
- Check your internet connection
- Try different search terms
- Bing may have rate-limited requests (wait a few minutes)

**Script fails to execute:**
- Ensure `curl` and `python3` are installed
- Check file permissions: `chmod +x scripts/search.sh`

## Limitations

- Maximum 30 results per query (pagination supported)
- Results are from Bing China (cn.bing.com)
- Some advanced search operators may not work
- Rate limiting may occur with frequent requests
- Pagination adds slight delay (0.5s between pages)
