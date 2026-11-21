import type {MessageKey} from '../i18n';

/** The commands the web console offers; a trailing space means an argument follows. */
const SLASH_COMMANDS: {cmd: string; desc: MessageKey}[] = [
  {cmd: '/help', desc: 'slash_help'},
  {cmd: '/status', desc: 'slash_status'},
  {cmd: '/context', desc: 'slash_context'},
  {cmd: '/clear', desc: 'slash_context_clear'},
  {cmd: '/compact', desc: 'slash_compact'},
  {cmd: '/skill list', desc: 'slash_skill_list'},
  {cmd: '/skill list --remote', desc: 'slash_skill_list_remote'},
  {cmd: '/skill search ', desc: 'slash_skill_search'},
  {cmd: '/skill install ', desc: 'slash_skill_install'},
  {cmd: '/skill uninstall ', desc: 'slash_skill_uninstall'},
  {cmd: '/skill info ', desc: 'slash_skill_info'},
  {cmd: '/skill enable ', desc: 'slash_skill_enable'},
  {cmd: '/skill disable ', desc: 'slash_skill_disable'},
  {cmd: '/memory dream ', desc: 'slash_memory_dream'},
  {cmd: '/knowledge', desc: 'slash_knowledge'},
  {cmd: '/knowledge list', desc: 'slash_knowledge_list'},
  {cmd: '/knowledge on', desc: 'slash_knowledge_on'},
  {cmd: '/knowledge off', desc: 'slash_knowledge_off'},
  {cmd: '/config', desc: 'slash_config'},
  {cmd: '/cancel', desc: 'slash_cancel'},
  {cmd: '/steer ', desc: 'slash_steer'},
  {cmd: '/logs', desc: 'slash_logs'},
  {cmd: '/version', desc: 'slash_version'},
];

/** Commands the typed text could still become; none once it is a finished command. */
export function matchSlash(text: string) {
  if (!text.startsWith('/') || text.includes('\n')) {
    return [];
  }
  const q = text.toLowerCase();
  const hits = SLASH_COMMANDS.filter(c => c.cmd.toLowerCase().startsWith(q));
  return hits.length === 1 && hits[0].cmd === text ? [] : hits;
}

/** An `@` at the start or after whitespace, followed by what has been typed of the name so far. */
export function matchMention(text: string, cursor: number): {start: number; query: string} | null {
  const before = text.slice(0, cursor);
  const m = /(?:^|\s)@([^\s@]*)$/.exec(before);
  return m ? {start: cursor - m[1].length - 1, query: m[1]} : null;
}
