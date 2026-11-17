import {linkAsPage, menuSections} from '../src/navigation/menuViews';
import type {MenuDoc} from '../src/protocol/resources';

jest.mock('../src/store/menuStore', () => ({menuGroupLabel: (g: {title: string}) => g.title}));

const doc: MenuDoc = {
  groups: [
    {
      id: 'chat',
      title: '',
      items: [
        {id: 'chat', type: 'builtin', view: 'chat', title: '', icon: ''},
        {id: 'artifacts', type: 'builtin', view: 'artifacts', title: '', icon: '', hidden: true},
        {
          id: 'a1',
          type: 'artifact',
          title: '周报',
          icon: '',
          path: '/ws/report.html',
          file: {file_name: 'report.html', kind: 'html', exists: true, preview_url: '/preview/t/report.html', raw_url: ''},
        },
        {
          id: 'a2',
          type: 'artifact',
          title: '旧文件',
          icon: '',
          path: '/ws/gone.html',
          file: {file_name: 'gone.html', kind: 'html', exists: false, preview_url: '', raw_url: ''},
        },
        {id: 'u1', type: 'url', title: '看板', icon: '', url: 'https://example.com/board'},
        {id: 'u2', type: 'url', title: '文档', icon: '', url: 'https://example.com/docs', open: 'tab'},
      ],
    },
  ],
};

describe('menuSections', () => {
  const entries = menuSections(doc)[0].entries;
  const byKey = (key: string) => entries.find(e => e.key === key);

  it('keeps Artifacts out of the chat group', () => {
    expect(byKey('artifacts')).toBeUndefined();
  });

  it('lists Artifacts right below Knowledge, even when the shared menu hides it', () => {
    const withManage: MenuDoc = {
      groups: [
        doc.groups[0],
        {
          id: 'manage',
          title: 'Manage',
          items: [
            {id: 'agents', type: 'builtin', view: 'agents', title: '', icon: ''},
            {id: 'knowledge', type: 'builtin', view: 'knowledge', title: '', icon: ''},
            {id: 'memory', type: 'builtin', view: 'memory', title: '', icon: ''},
          ],
        },
      ],
    };
    const manage = menuSections(withManage).find(s => s.id === 'manage')!;
    expect(manage.entries.map(e => e.key)).toEqual(['agents', 'knowledge', 'artifacts', 'memory']);
    expect(manage.entries[2]).toMatchObject({kind: 'route', route: 'Artifacts'});
  });

  it("leaves Artifacts out when this device's switch is off", () => {
    expect(menuSections(doc, false, false).flatMap(s => s.entries.map(e => e.key))).not.toContain('artifacts');
  });

  it('opens a Manage section for Artifacts when the menu has none', () => {
    const sections = menuSections(doc);
    expect(sections[sections.length - 1]).toMatchObject({id: 'manage', entries: [{key: 'artifacts'}]});
  });

  it('turns a pinned artifact into a file the app opens itself', () => {
    expect(byKey('a1')).toMatchObject({
      kind: 'file',
      file: {name: '周报', kind: 'html', path: '/ws/report.html', previewUrl: '/preview/t/report.html'},
    });
    expect(byKey('a2')).toMatchObject({kind: 'file', file: null});
  });

  it('only sends links set to open in a tab out of the app', () => {
    expect(byKey('u1')).toMatchObject({kind: 'link', external: false});
    expect(byKey('u2')).toMatchObject({kind: 'link', external: true});
  });

  it('leaves out channels on the built-in agent, which runs none', () => {
    const withChannels: MenuDoc = {
      groups: [
        {
          id: 'manage',
          title: 'Manage',
          items: [
            {id: 'channels', type: 'builtin', view: 'channels', title: '', icon: ''},
            {id: 'tasks', type: 'builtin', view: 'tasks', title: '', icon: ''},
          ],
        },
      ],
    };
    const keys = (local: boolean) => menuSections(withChannels, local)[0].entries.map(e => e.key);
    expect(keys(false)).toEqual(['artifacts', 'channels', 'tasks']);
    expect(keys(true)).toEqual(['artifacts', 'tasks']);
  });
});

describe('linkAsPage', () => {
  it('shows a web link through the page viewer', () => {
    expect(linkAsPage('看板', 'https://example.com/board')).toEqual({
      name: '看板',
      kind: 'html',
      rawUrl: 'https://example.com/board',
    });
  });
});
