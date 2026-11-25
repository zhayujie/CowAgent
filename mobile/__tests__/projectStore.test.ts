import {createProject, getProjects, selectProject} from '../src/api/cowApi';
import type {ProjectState} from '../src/protocol/resources';
import {useProjectStore} from '../src/store/projectStore';
import {resetServerData} from '../src/store/reset';

jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);
jest.mock('react-native-keychain', () => ({}));
jest.mock('../src/api/cowApi', () => ({
  getProjects: jest.fn(),
  selectProject: jest.fn(),
  createProject: jest.fn(),
}));

const state = (current: string | null): ProjectState => ({
  current: current ? {path: `/p/${current}`, name: current} : null,
  default_workspace: '/home/cow',
  projects_root: '/p',
  recents: [],
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(r => (resolve = r));
  return {promise, resolve};
}

beforeEach(() => {
  jest.resetAllMocks();
  resetServerData();
});

it('keeps a switch that answers before an older read', async () => {
  const read = deferred<ProjectState>();
  jest.mocked(getProjects).mockReturnValue(read.promise);
  jest.mocked(selectProject).mockResolvedValue(state('app'));

  const loading = useProjectStore.getState().load('s1', null);
  await useProjectStore.getState().select('s1', null, '/p/app');
  read.resolve(state(null));
  await loading;

  expect(useProjectStore.getState().bySession.s1.current?.name).toBe('app');
});

it('reads after a switch still in flight', async () => {
  const write = deferred<ProjectState>();
  jest.mocked(selectProject).mockReturnValue(write.promise);
  jest.mocked(getProjects).mockResolvedValue(state('app'));

  const switching = useProjectStore.getState().select('s1', null, '/p/app');
  const loading = useProjectStore.getState().load('s1', null);
  await Promise.resolve();
  expect(getProjects).not.toHaveBeenCalled();

  write.resolve(state('app'));
  await Promise.all([switching, loading]);

  expect(getProjects).toHaveBeenCalledTimes(1);
  expect(useProjectStore.getState().bySession.s1.current?.name).toBe('app');
});

it('shows a new chat in its space before the server answers', async () => {
  jest.mocked(getProjects).mockResolvedValue(state(null));
  await useProjectStore.getState().load('s1', null);
  const write = deferred<ProjectState>();
  jest.mocked(selectProject).mockReturnValue(write.promise);

  const starting = useProjectStore.getState().startIn('s2', null, {path: '/p/app', name: 'app'});

  expect(useProjectStore.getState().bySession.s2.current).toEqual({path: '/p/app', name: 'app'});
  expect(selectProject).toHaveBeenCalledWith('s2', '/p/app', undefined);
  write.resolve(state('app'));
  await starting;
});

it('drops an answer that lands after a sign-out', async () => {
  const read = deferred<ProjectState>();
  jest.mocked(getProjects).mockReturnValue(read.promise);

  const loading = useProjectStore.getState().load('s1', null);
  resetServerData();
  read.resolve(state('old'));
  await loading;

  expect(useProjectStore.getState().bySession).toEqual({});
});

it('stores what a new project answers', async () => {
  jest.mocked(createProject).mockResolvedValue(state('demo'));

  await useProjectStore.getState().create('s1', 'a1', 'demo');

  expect(createProject).toHaveBeenCalledWith('s1', 'demo', 'a1');
  expect(useProjectStore.getState().bySession.s1.current?.name).toBe('demo');
});
