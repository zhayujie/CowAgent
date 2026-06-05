---
name: ppt-generator
description: Generate PowerPoint presentations from structured content. Use when the user asks to create, build, or generate a PPT, PowerPoint, slide deck, presentation, or slides for any topic. Supports multiple slide types including title slides, content slides with bullet points, two-column layouts, image slides, section headers, icon grids, statistics/KPI cards, charts (bar/pie/line), data tables, and ending slides. Supports 7 color themes.
metadata:
  requires:
    bins: ["python3"]
  emoji: 📊
---

# PPT Generator

Generate professional PowerPoint presentations with backgrounds, icons, charts, tables, and rich visual elements.

## Setup

```bash
pip install python-pptx
```

## Usage

```bash
python "<base_dir>/scripts/generate_ppt.py" input.json output.pptx [--theme <theme>]
```

### Available Themes

`blue` (default) | `dark` | `green` | `orange` | `purple` | `red` | `minimal`

Theme can also be set in JSON: `"theme": "dark"`

## Slide Types

### 1. title — Title Slide
Dark background with decorative circles and accent bars.
```json
{"type": "title", "title": "Main Title", "subtitle": "Subtitle", "author": "Author", "date": "2025"}
```
Top-level `title`, `subtitle`, `author`, `date` auto-create a title slide.

### 2. section — Section Header
Dark background for chapter dividers.
```json
{"type": "section", "title": "Section Name", "icon": "🚀", "subtitle": "Optional subtitle"}
```

### 3. content — Content with Bullets
White background with left accent bar and styled bullets.
```json
{
  "type": "content", "title": "Slide Title", "icon": "📌",
  "bullets": ["Point 1", "Point 2"],
  "bullet_icon": "▸",
  "note": "Optional footer note"
}
```

### 4. two_column — Two-Column Cards
Side-by-side card layout for comparisons.
```json
{
  "type": "two_column", "title": "Comparison",
  "left":  {"title": "Left",  "icon": "✅", "bullets": ["A", "B"]},
  "right": {"title": "Right", "icon": "❌", "bullets": ["C", "D"]}
}
```

### 5. icon_grid — Icon Grid
Grid of icon + title + description cards. Auto-layouts based on item count.
```json
{
  "type": "icon_grid", "title": "Features",
  "columns": 3,
  "items": [
    {"icon": "🤖", "title": "AI Agent", "bullets": ["Autonomous tasks"]},
    {"icon": "🌐", "title": "Multimodal", "bullets": ["Text + Image + Audio"]},
    {"icon": "🔧", "title": "Tools", "bullets": ["MCP protocol"]}
  ]
}
```

### 6. stats — Statistics / KPI Cards
Large numbers with icons and descriptions.
```json
{
  "type": "stats", "title": "Key Metrics",
  "stats": [
    {"icon": "📈", "value": "$190B", "label": "Market Size", "description": "Global AI market 2025"},
    {"icon": "🏢", "value": "70%", "label": "Adoption Rate", "description": "Enterprise AI adoption"},
    {"icon": "💰", "value": "3.5x", "label": "ROI", "description": "Average return on investment"}
  ]
}
```

### 7. chart — Data Charts
Bar, pie, line, or area charts with theme colors.
```json
{
  "type": "chart", "title": "Growth Trend",
  "chart_type": "bar",
  "categories": ["2022", "2023", "2024", "2025"],
  "series": [
    {"name": "Revenue", "values": [50, 80, 120, 190]},
    {"name": "Cost", "values": [30, 45, 60, 75]}
  ]
}
```
chart_type options: `bar` | `line` | `pie` | `area`

### 8. table — Data Table
Styled table with themed header and alternating row colors.
```json
{
  "type": "table", "title": "Comparison",
  "headers": ["Model", "Parameters", "Price"],
  "rows": [
    ["GPT-4o", "1.8T", "$2.50/1M"],
    ["Claude 3.5", "Unknown", "$3.00/1M"],
    ["Gemini Pro", "Unknown", "$1.25/1M"]
  ]
}
```

### 9. image — Image Slide
```json
{"type": "image", "title": "Architecture", "image_path": "/path/to/img.png", "caption": "System overview"}
```

### 10. timeline — Timeline with Icons
Horizontal timeline with icon milestones, dates, and descriptions.
```json
{
  "type": "timeline", "title": "AI Development History",
  "events": [
    {"icon": "🎯", "date": "2017", "description": "Transformer architecture"},
    {"icon": "🚀", "date": "2020", "description": "GPT-3 released"},
    {"icon": "💡", "date": "2022", "description": "ChatGPT launched"},
    {"icon": "🌟", "date": "2024", "description": "Multimodal AI"}
  ]
}
```

### 11. process — Process Flow
Numbered step-by-step process with icons and arrows.
```json
{
  "type": "process", "title": "AI Implementation Steps",
  "steps": [
    {"icon": "📊", "title": "Assessment", "description": "Evaluate current AI readiness"},
    {"icon": "🎯", "title": "Planning", "description": "Identify high-impact use cases"},
    {"icon": "🔧", "title": "Development", "description": "Build pilot projects"},
    {"icon": "🚀", "title": "Deployment", "description": "Scale to production"}
  ]
}
```

### 12. comparison — Feature Comparison Cards
Grid of cards with icons, titles, values/metrics, and descriptions.
```json
{
  "type": "comparison", "title": "Model Comparison",
  "items": [
    {"icon": "🧠", "title": "GPT-4", "value": "$2.50/1M", "description": "Most capable"},
    {"icon": "⚡", "title": "Claude 3.5", "value": "$3.00/1M", "description": "Fast reasoning"},
    {"icon": "🌐", "title": "Gemini Pro", "value": "$1.25/1M", "description": "Cost effective"}
  ]
}
```

### 13. end — Ending / Thank You Slide
Dark background with decorative elements.
```json
{"type": "end", "title": "Thank You", "subtitle": "Questions?", "contact": "email@example.com"}
```
Auto-added as last slide if not explicitly included. Set `end_title`, `end_subtitle`, `end_contact` at top level to customize.

## Best Practices

- **3-5 bullets** per slide for readability
- **Use icons** (emoji) to make slides visually engaging
- **Use stats slides** for key numbers and KPIs
- **Use chart slides** for data visualization
- **Use icon_grid** for feature overviews (3-6 items)
- **Use section slides** to divide content into chapters
- **Mix slide types** — don't use only content slides
- **End with end slide** — provides a professional closing

## Output

- 16:9 widescreen aspect ratio
- 7 professional color themes
- Decorative backgrounds, accent bars, and shapes
- Emoji icons throughout
- Charts with theme-matched colors
- Tables with alternating row colors
- Compatible with PowerPoint, Keynote, Google Slides
