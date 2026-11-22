import {createProject, getProjects, selectProject} from '../src/api/cowApi';
import type {ProjectState} from '../src/protocol/resources';
import {useWorkspaceStore, workspaceKey} from '../src/store/workspaceStore';

jest.mock('../src/api/cowApi', () => ({
  createProject: jest.fn(),
  getProjects: jest.fn(),
  selectProject: jest.fn(),
}));
jest.mock('../src/store/agentStore', () => ({
  agentParam: (id: string | null) => id ?? undefined,
}));

const state = (name: string): ProjectState => ({
  status: 'success',
  current: {name, path: `/projects/${name}`},
  recents: [],
  default_workspace: '/workspace',
  projects_root: '/projects',
});

beforeEach(() => {
  jest.clearAllMocks();
  useWorkspaceStore.setState({byChat: {}});
});

it('keeps project bindings separate for Agents and sessions', async () => {
  jest.mocked(getProjects).mockResolvedValueOnce(state('one')).mockResolvedValueOnce(state('two'));

  await useWorkspaceStore.getState().load('s1', 'a1');
  await useWorkspaceStore.getState().load('s1', 'a2');

  expect(getProjects).toHaveBeenNthCalledWith(1, 's1', 'a1');
  expect(getProjects).toHaveBeenNthCalledWith(2, 's1', 'a2');
  expect(useWorkspaceStore.getState().byChat[workspaceKey('s1', 'a1')]?.current?.name).toBe('one');
  expect(useWorkspaceStore.getState().byChat[workspaceKey('s1', 'a2')]?.current?.name).toBe('two');
});

it('selects the default workspace and creates a trimmed project name', async () => {
  jest.mocked(selectProject).mockResolvedValue(state('default'));
  jest.mocked(createProject).mockResolvedValue({...state('new'), path: '/projects/new'});

  await useWorkspaceStore.getState().select('s1', 'a1', null);
  await useWorkspaceStore.getState().create('s1', 'a1', '  new  ');

  expect(selectProject).toHaveBeenCalledWith('s1', null, 'a1');
  expect(createProject).toHaveBeenCalledWith('s1', 'new', 'a1');
  expect(useWorkspaceStore.getState().byChat[workspaceKey('s1', 'a1')]?.current?.name).toBe('new');
});

it('ignores a slow load that finishes after a newer one', async () => {
  let finishFirst!: (value: ProjectState) => void;
  const first = new Promise<ProjectState>(resolve => {
    finishFirst = resolve;
  });
  jest.mocked(getProjects).mockReturnValueOnce(first).mockResolvedValueOnce(state('new'));

  const oldLoad = useWorkspaceStore.getState().load('s1', 'a1');
  const newLoad = useWorkspaceStore.getState().load('s1', 'a1');
  await newLoad;
  finishFirst(state('old'));
  await oldLoad;

  expect(useWorkspaceStore.getState().byChat[workspaceKey('s1', 'a1')]?.current?.name).toBe('new');
});
