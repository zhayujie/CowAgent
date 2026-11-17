/** An id for a new Agent: its name as a lowercase ASCII slug, unique among `taken`.
 *  A name with no ASCII letters or digits gets a time-based id instead. */
export function newAgentId(name: string, taken: readonly string[], now = Date.now()): string {
  const slug = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48)
    .replace(/-+$/, '');
  const base = slug || `agent-${now.toString(36)}`;
  let id = base;
  for (let n = 2; taken.includes(id); n++) {
    id = `${base}-${n}`;
  }
  return id;
}
