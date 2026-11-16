import type {StackScreenProps} from '@react-navigation/stack';
import React from 'react';
import {View} from 'react-native';
import {RunList} from '../components/RunList';
import {PageHeader} from '../components/ui';
import type {RootStackParamList} from '../navigation/types';
import {makeStyles} from '../theme/theme';

type Props = StackScreenProps<RootStackParamList, 'TaskRuns'>;

export function TaskRunsScreen({route, navigation}: Props) {
  const styles = useStyles();
  return (
    <View style={styles.root}>
      <PageHeader title={route.params?.title || '执行记录'} onBack={navigation.goBack} />
      <RunList taskId={route.params?.taskId} />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
}));
