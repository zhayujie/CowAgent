import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useEffect, useState} from 'react';
import {KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, TextInput, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {getAgentFile, saveAgentFile} from '../api/cowApi';
import {ApiError} from '../api/http';
import {Markdown} from '../components/Markdown';
import {EditActions} from '../components/DocPage';
import {MONO} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {EmptyState, PageHeader} from '../components/ui';
import {tr, trf} from '../i18n';
import type {RootStackParamList} from '../navigation/types';
import {describeConnectError} from '../store/serverStore';
import {makeStyles, useTheme} from '../theme/theme';
import {CORE_FILE_META} from './AgentDetailScreen';

type Props = StackScreenProps<RootStackParamList, 'AgentFile'>;

export function AgentFileScreen({route, navigation}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const {agentId, name} = route.params;
  const label = CORE_FILE_META.find(f => f.name === name)?.label ?? name;
  const [file, setFile] = useState<{content: string; revision: string} | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [stale, setStale] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await getAgentFile(agentId, name);
      setFile({content: res.content ?? '', revision: res.revision});
      setError(null);
      setStale(false);
    } catch (e) {
      setError(describeConnectError(e));
    }
  }, [agentId, name]);

  useEffect(() => {
    load();
  }, [load]);

  const startEdit = () => {
    setDraft(file?.content ?? '');
    setEditing(true);
  };

  const save = async () => {
    if (!file) {
      return;
    }
    if (draft === file.content) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      const res = await saveAgentFile(agentId, name, draft, file.revision);
      setFile({content: res.content ?? draft, revision: res.revision});
      setEditing(false);
      showToast(tr('common_saved'));
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setStale(true);
      } else {
        showToast(trf('common_save_failed_detail', {error: describeConnectError(e)}));
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <View style={styles.root}>
      <PageHeader title={label} onBack={navigation.goBack} />
      <View style={styles.toolbar}>
        <Text style={styles.filename} numberOfLines={1}>
          {name}
        </Text>
        {!!file && (
          <EditActions
            editing={editing}
            editable
            saving={saving}
            onEdit={startEdit}
            onSave={save}
            onCancel={() => setEditing(false)}
          />
        )}
      </View>
      {stale && (
        <Pressable onPress={load} style={styles.stale}>
          <Text style={styles.staleText}>{tr('agent_file_stale')}</Text>
        </Pressable>
      )}
      {!file ? (
        <EmptyState loading={!error} title={tr('common_load_failed')} hint={error ?? undefined} />
      ) : editing ? (
        <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
          <TextInput
            value={draft}
            onChangeText={setDraft}
            multiline
            autoFocus
            autoCapitalize="none"
            autoCorrect={false}
            textAlignVertical="top"
            selectionColor={t.accent}
            cursorColor={t.accent}
            placeholder={tr('agent_file_placeholder')}
            placeholderTextColor={t.t4}
            style={[styles.editor, {paddingBottom: insets.bottom + 24}]}
          />
        </KeyboardAvoidingView>
      ) : (
        <ScrollView contentContainerStyle={[styles.body, {paddingBottom: insets.bottom + 32}]}>
          {file.content.trim() ? (
            <Markdown value={file.content} />
          ) : (
            <EmptyState title={tr('agent_file_empty')} hint={tr('agent_file_empty_hint')} />
          )}
        </ScrollView>
      )}
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  flex: {flex: 1},
  toolbar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    minHeight: 44,
    paddingHorizontal: 18,
    paddingBottom: 8,
    borderBottomWidth: 1,
    borderBottomColor: t.line1,
  },
  filename: {flex: 1, fontFamily: MONO, fontSize: 12, color: t.t4},
  stale: {
    marginHorizontal: 18,
    marginBottom: 10,
    padding: 12,
    borderRadius: 10,
    backgroundColor: t.dangerSoft,
  },
  staleText: {fontSize: 13, lineHeight: 19, color: t.danger},
  body: {paddingHorizontal: 18, paddingTop: 6, flexGrow: 1},
  editor: {
    flex: 1,
    paddingHorizontal: 18,
    paddingTop: 8,
    fontFamily: MONO,
    fontSize: 13,
    lineHeight: 21,
    color: t.t1,
  },
}));
