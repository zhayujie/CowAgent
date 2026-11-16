import {createNavigationContainerRef} from '@react-navigation/native';
import type {RootStackParamList} from './types';

/** For opening screens from places that sit outside a screen, like a link inside a reply. */
export const navigationRef = createNavigationContainerRef<RootStackParamList>();
