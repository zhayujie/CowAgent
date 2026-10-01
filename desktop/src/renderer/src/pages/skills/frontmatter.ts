/** Drop the surrounding quotes a YAML scalar may carry. */
function yamlScalar(raw: string): string {
  return raw.trim().replace(/^(['"])(.*)\1$/, '$2')
}

/**
 * Split a skill's SKILL.md into its YAML frontmatter fields and the markdown
 * body. The `---` header is metadata, not prose: handed to the markdown
 * renderer as-is it becomes a giant bold heading and a horizontal rule. Pull it
 * out so name/description show as a proper header instead.
 *
 * Frontmatter nests: `metadata.cowagent.requires.anyEnv` is a list four levels
 * down. Read line by line with no regard for indentation, each container key
 * showed up as an empty row and the list under it vanished. So this walks the
 * indentation instead: a nested map becomes one row per leaf, keyed by its
 * dotted path; a list or a block scalar (`|`, `>`) becomes one row with its
 * lines joined. Only leaves are rows - a key that merely holds others has
 * nothing to say on its own.
 */
export function parseSkillFrontmatter(content: string): { fields: Array<[string, string]>; body: string } {
  const text = content || ''
  const match = text.match(/^---\s*\r?\n([\s\S]*?)\r?\n---\s*\r?\n?/)
  if (!match) return { fields: [], body: text }

  const lines = match[1].split(/\r?\n/)
  const fields: Array<[string, string]> = []
  // The key at each indentation level above the current line.
  const path: Array<{ indent: number; key: string }> = []
  // A key whose value is still being collected from the lines below it: the
  // items of a list, or the lines of a block scalar.
  let open: { key: string; indent: number; items: string[]; block: boolean } | null = null

  const flush = () => {
    if (!open) return
    const joined = open.block ? open.items.join(' ').trim() : open.items.join(', ')
    fields.push([open.key, joined])
    open = null
  }

  for (const raw of lines) {
    const line = raw.trim()
    if (!line) continue
    const indent = raw.length - raw.trimStart().length
    // Inside a block scalar a `#` line is text, not a comment.
    if (open && open.block && indent > open.indent) {
      open.items.push(line)
      continue
    }
    if (line.startsWith('#')) continue
    // A list's dashes may sit level with their key or under it.
    if (open && !open.block && indent >= open.indent && line.startsWith('- ')) {
      open.items.push(yamlScalar(line.slice(2)))
      continue
    }
    // Anything else ends an open value: what follows is the next key, or -
    // under a key opened as a possible list - the first key of a nested map.
    flush()

    while (path.length && path[path.length - 1].indent >= indent) path.pop()
    const idx = line.indexOf(':')
    if (idx === -1) continue
    const key = yamlScalar(line.slice(0, idx))
    if (!key) continue
    const dotted = [...path.map((p) => p.key), key].join('.')
    const rest = line.slice(idx + 1).trim()

    if (!rest) {
      // Either a nested map, or a list that starts on the next line: which one
      // is decided by the line that follows. Open both readings and let the
      // next indented line settle it.
      path.push({ indent, key })
      open = { key: dotted, indent, items: [], block: false }
    } else if (/^[|>][-+0-9]*$/.test(rest)) {
      open = { key: dotted, indent, items: [], block: true }
    } else {
      fields.push([dotted, yamlScalar(rest)])
    }
  }
  flush()

  // A container key opened as a possible list but then held a map instead: its
  // children have their own rows, so drop the empty one it left behind.
  return { fields: fields.filter(([, value]) => value !== ''), body: text.slice(match[0].length) }
}
