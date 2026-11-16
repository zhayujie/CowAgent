import {faFileLines, faFolder, faFolderOpen} from '@fortawesome/free-regular-svg-icons';
import {faChevronRight, faPen} from '@fortawesome/free-solid-svg-icons';
import {useFocusEffect} from '@react-navigation/native';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useMemo, useState} from 'react';
import {Pressable, RefreshControl, ScrollView, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {deleteSkill, getSkillFiles, getSkills, setSkillEnabled} from '../api/cowApi';
import {Icon} from '../components/Icon';
import {ActionButton, ConfirmSheet, Notice, SwitchRow} from '../components/settings';
import {SkillIcon} from '../components/SkillIcon';
import {showToast, ToastHost} from '../components/Toast';
import {EmptyState, GroupLabel, IconButton, PageHeader} from '../components/ui';
import type {RootStackParamList} from '../navigation/types';
import type {Skill, SkillFile} from '../protocol/resources';
import {describeConnectError} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {formatBytes} from '../utils/format';
import {SKILL_SOURCE_LABEL, skillDescription, skillName} from '../utils/skills';
import {skillErrorText} from './SkillsScreen';

type Props = StackScreenProps<RootStackParamList, 'SkillDetail'>;

export function SkillDetailScreen({route, navigation}: Props) {
  const {name, agentId} = route.params;
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const [skill, setSkill] = useState<Skill | null | undefined>(undefined);
  const [files, setFiles] = useState<SkillFile[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [folded, setFolded] = useState<Set<string>>(new Set());
  const [confirmDelete, setConfirmDelete] = useState(false);

  const load = useCallback(async () => {
    try {
      // No single-skill endpoint: the library list is what carries its state.
      const [list, tree] = await Promise.all([getSkills(agentId), getSkillFiles(name, agentId).catch(() => null)]);
      setSkill(list.skills.find(s => s.name === name) ?? null);
      setFiles(tree?.files ?? []);
      setError(null);
    } catch (e) {
      setError(describeConnectError(e));
    }
  }, [name, agentId]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  const visibleFiles = useMemo(
    () => (files ?? []).filter(f => ![...folded].some(dir => f.path.startsWith(`${dir}/`))),
    [files, folded],
  );

  const title = skill ? skillName(skill) : name;

  if (skill === null || (skill === undefined && error)) {
    return (
      <View style={styles.root}>
        <PageHeader title={title} onBack={navigation.goBack} />
        <EmptyState title={error ? '加载失败' : '这个技能已不存在'} hint={error ?? '可能已在别处删除'} />
      </View>
    );
  }
  if (!skill) {
    return (
      <View style={styles.root}>
        <PageHeader title={title} onBack={navigation.goBack} />
        <EmptyState loading title="" />
      </View>
    );
  }

  const shipped = !!skill.ships_with_install;
  const deletable = skill.deletable !== false && !shipped;
  const desc = skillDescription(skill);
  const tags = [
    shipped ? '内置' : skill.source ? SKILL_SOURCE_LABEL[skill.source] ?? skill.source : null,
    skill.version ? `v${skill.version}` : null,
    skill.display_name && skill.display_name !== skill.name ? skill.name : null,
  ].filter(Boolean) as string[];

  const toggle = async (enabled: boolean) => {
    setSkill({...skill, enabled});
    try {
      await setSkillEnabled(skill.name, enabled, agentId);
    } catch (e) {
      setSkill({...skill, enabled: !enabled});
      showToast(`${enabled ? '启用' : '停用'}失败：${skillErrorText(e)}`);
    }
  };

  const openFile = (file: SkillFile) => {
    if (file.is_dir) {
      setFolded(prev => {
        const next = new Set(prev);
        if (!next.delete(file.path)) {
          next.add(file.path);
        }
        return next;
      });
      return;
    }
    if (!file.text) {
      showToast('这个文件不是文本，手机上无法预览');
      return;
    }
    navigation.navigate('SkillFile', {
      name: skill.name,
      path: file.path === 'SKILL.md' ? undefined : file.path,
      title: file.name,
      agentId,
    });
  };

  return (
    <View style={styles.root}>
      <PageHeader
        title={title}
        onBack={navigation.goBack}
        right={
          shipped ? null : (
            <IconButton
              icon={faPen}
              label="编辑 SKILL.md"
              filled
              size={13}
              color={t.t1}
              onPress={() => navigation.navigate('SkillFile', {name: skill.name, title: 'SKILL.md', agentId, edit: true})}
            />
          )
        }
      />
      <ScrollView
        contentContainerStyle={{paddingBottom: insets.bottom + 32}}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={async () => {
              setRefreshing(true);
              await load();
              setRefreshing(false);
            }}
            tintColor={t.t3}
            colors={[t.green]}
          />
        }>
        <View style={styles.hero}>
          <SkillIcon skill={skill} size={52} />
          <View style={styles.heroText}>
            <Text style={styles.heroName}>{skillName(skill)}</Text>
            {tags.length > 0 && (
              <View style={styles.tags}>
                {tags.map(tag => (
                  <Text key={tag} style={styles.tag}>
                    {tag}
                  </Text>
                ))}
              </View>
            )}
          </View>
        </View>
        <Text style={[styles.desc, !desc && styles.dim]} selectable>
          {desc || '没有描述'}
        </Text>

        <View style={styles.switchWrap}>
          <SwitchRow
            title="启用"
            detail="停用后 Agent 不会再使用这个技能，文件保留"
            value={skill.enabled}
            onValueChange={toggle}
            last
          />
        </View>
        {shipped && <Notice style={styles.notice}>内置技能随安装包更新，每次启动都会恢复原样，所以只能查看，不能修改或删除。</Notice>}

        <GroupLabel style={styles.group}>{files ? `文件 · ${files.filter(f => !f.is_dir).length}` : '文件'}</GroupLabel>
        {!files ? (
          <EmptyState loading title="" />
        ) : !files.length ? (
          <Text style={styles.note}>没有读到文件列表</Text>
        ) : (
          <View style={styles.tree}>
            {visibleFiles.map((f, i) => {
              const isFolded = folded.has(f.path);
              return (
                <Pressable
                  key={f.path}
                  accessibilityRole="button"
                  accessibilityState={f.is_dir ? {expanded: !isFolded} : undefined}
                  onPress={() => openFile(f)}
                  style={({pressed}) => [
                    styles.file,
                    {paddingLeft: 12 + f.depth * 16},
                    i > 0 && styles.fileDivider,
                    pressed && styles.pressed,
                  ]}>
                  <Icon
                    icon={f.is_dir ? (isFolded ? faFolder : faFolderOpen) : faFileLines}
                    size={13}
                    color={f.is_dir ? t.t2 : f.text ? t.t3 : t.t4}
                  />
                  <Text
                    style={[styles.fileName, f.is_dir && styles.dirName, !f.is_dir && !f.text && styles.dim]}
                    numberOfLines={1}>
                    {f.name}
                  </Text>
                  {!f.is_dir && <Text style={styles.fileSize}>{formatBytes(f.size)}</Text>}
                  {!f.is_dir && f.text && <Icon icon={faChevronRight} size={9} color={t.t4} />}
                </Pressable>
              );
            })}
          </View>
        )}

        {deletable && (
          <View style={styles.danger}>
            <ActionButton label="删除这个技能" tone="danger" onPress={() => setConfirmDelete(true)} />
          </View>
        )}
      </ScrollView>

      <ConfirmSheet
        visible={confirmDelete}
        title="删除技能"
        message={`「${skillName(skill)}」和它目录里的所有文件都会被删除，Agent 也不能再使用它。`}
        confirmLabel="删除"
        danger
        onConfirm={async () => {
          try {
            await deleteSkill(skill.name, agentId);
            setConfirmDelete(false);
            navigation.goBack();
          } catch (e) {
            setConfirmDelete(false);
            showToast(`删除失败：${skillErrorText(e)}`);
          }
        }}
        onClose={() => setConfirmDelete(false)}
      />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  hero: {flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 18, paddingTop: 10},
  heroText: {flex: 1, minWidth: 0},
  heroName: {fontSize: 20, fontWeight: '700', letterSpacing: -0.4, color: t.t1},
  tags: {flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 6},
  tag: {
    fontSize: 11,
    color: t.t3,
    paddingHorizontal: 6,
    paddingVertical: 1.5,
    borderRadius: 5,
    overflow: 'hidden',
    backgroundColor: t.bg2,
  },
  desc: {fontSize: 14, lineHeight: 22, color: t.t2, paddingHorizontal: 18, paddingTop: 14},
  dim: {color: t.t4},
  switchWrap: {marginTop: 14, borderTopWidth: 1, borderTopColor: t.line1},
  notice: {marginTop: 4},
  group: {marginTop: 22},
  note: {fontSize: 13, color: t.t3, paddingHorizontal: 18},
  tree: {
    marginHorizontal: 14,
    borderRadius: radius.md,
    backgroundColor: t.bg1,
    borderWidth: 1,
    borderColor: t.line1,
    overflow: 'hidden',
  },
  file: {flexDirection: 'row', alignItems: 'center', gap: 9, paddingRight: 12, paddingVertical: 11},
  fileDivider: {borderTopWidth: 1, borderTopColor: t.line1},
  pressed: {backgroundColor: t.bg2},
  fileName: {flex: 1, fontSize: 14, color: t.t1},
  dirName: {fontWeight: '600', color: t.t2},
  fileSize: {fontSize: 11, color: t.t4, fontVariant: ['tabular-nums']},
  danger: {paddingHorizontal: 18, marginTop: 32},
}));
