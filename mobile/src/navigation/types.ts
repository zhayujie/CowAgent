import type {ChatFile} from '../files/chatFile';
import type {AgentCoreFile, CapabilityKey, MemoryCategory, ScheduledTask, TaskRun} from '../protocol/resources';

export type RootStackParamList = {
  Login: undefined;
  Chat: {sessionId: string; isNew?: boolean};
  Sessions: undefined;
  /** `focusPath` narrows the list to one file, as "view in artifacts" from a reply does. */
  Artifacts: {focusPath?: string; focusName?: string} | undefined;
  Skills: undefined;
  SkillDetail: {name: string};
  /** `path` is a file inside the skill's directory; omitted, its SKILL.md. */
  SkillFile: {name: string; path?: string; title: string; edit?: boolean};
  SkillCreate: undefined;
  Memory: undefined;
  Knowledge: undefined;
  /** `agentId` is the request-ready id: undefined for the default Agent. */
  MemoryDoc: {filename: string; category: MemoryCategory; title: string; agentId?: string};
  /** `edit` opens straight into the editor, as a freshly created page does. */
  KnowledgeDoc: {path: string; title: string; agentId?: string; edit?: boolean};
  FilePreview: {file: ChatFile};
  /** Any http(s) page; `title` shows until the page names itself. */
  WebPage: {url: string; title?: string};
  Tasks: undefined;
  /** Without `task` the form creates a new one. */
  TaskEdit: {task?: ScheduledTask} | undefined;
  TaskRuns: {taskId?: string; title?: string} | undefined;
  TaskRun: {runId: string; run?: TaskRun};
  Channels: undefined;
  /** `instanceId` picks one bot in multi-Agent mode; `add` opens the connect form for a new one. */
  Channel: {name: string; instanceId?: string; add?: boolean};
  Settings: undefined;
  Agents: undefined;
  AgentCreate: undefined;
  AgentDetail: {agentId: string};
  /** Per-Agent skill subset, matching the desktop Agents › Skills tab. */
  AgentSkills: {agentId: string};
  AgentFile: {agentId: string; name: AgentCoreFile};
  Models: undefined;
  Capability: {key: CapabilityKey};
  WebSearch: undefined;
  Runtime: undefined;
  Permissions: undefined;
  ExternalApi: undefined;
  Access: undefined;
  Devices: undefined;
  GuestShares: undefined;
  /** No `slug` creates a page; `focus` jumps to the password field. */
  GuestShareEdit: {slug?: string; focus?: 'password'};
  McpDetail: {name: string};
  McpEdit: {name?: string} | undefined;
  Logs: undefined;
  MenuEditor: undefined;
  Version: undefined;
};
