import {faCheck, faTriangleExclamation} from '@fortawesome/free-solid-svg-icons';
import React, {useEffect, useState} from 'react';
import {Pressable, ScrollView, Text, View} from 'react-native';
import {tr, trf} from '../i18n';
import type {SkillPreview} from '../protocol/resources';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {formatBytes} from '../utils/format';
import {SKILL_SOURCE_LABEL} from '../utils/skills';
import {Icon} from './Icon';
import {ActionButton} from './settings';
import {Sheet} from './Sheet';

/** What a fetched or uploaded package holds, reviewed before anything is installed. */
export function SkillInstallSheet({
  preview,
  onInstall,
  onClose,
}: {
  preview: SkillPreview | null;
  /** Rejects with a readable message, which the sheet shows in place. */
  onInstall: (names: string[]) => Promise<void>;
  onClose: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const skills = preview?.skills ?? [];
  const multi = skills.length > 1;

  useEffect(() => {
    setSelected(new Set((preview?.skills ?? []).map(s => s.name)));
    setError(null);
    setBusy(false);
  }, [preview]);

  const toggle = (name: string) =>
    setSelected(prev => {
      const next = new Set(prev);
      if (!next.delete(name)) {
        next.add(name);
      }
      return next;
    });

  const install = async () => {
    setBusy(true);
    setError(null);
    try {
      await onInstall([...selected]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <Sheet
      visible={!!preview}
      onClose={busy ? () => undefined : onClose}
      title={multi ? trf('skill_install_found', {n: skills.length}) : tr('skill_install_title')}>
      <ScrollView style={styles.list} contentContainerStyle={styles.listBody}>
        {skills.map(s => {
          const on = selected.has(s.name);
          const meta = [
            s.source ? SKILL_SOURCE_LABEL[s.source] ?? s.source : null,
            s.file_count ? trf('skill_file_count', {n: s.file_count}) : null,
            s.size ? formatBytes(s.size) : null,
          ].filter(Boolean);
          return (
            <Pressable
              key={s.name}
              disabled={!multi}
              accessibilityRole={multi ? 'checkbox' : undefined}
              accessibilityState={multi ? {checked: on} : undefined}
              onPress={() => toggle(s.name)}
              style={[styles.item, multi && on && styles.itemOn]}>
              {multi && (
                <View style={[styles.check, on && styles.checkOn]}>
                  {on && <Icon icon={faCheck} size={10} color={t.onAccent} />}
                </View>
              )}
              <View style={styles.text}>
                <Text style={styles.name} numberOfLines={1}>
                  {s.display_name || s.name}
                </Text>
                {!!s.description && (
                  <Text style={styles.desc} numberOfLines={3}>
                    {s.description}
                  </Text>
                )}
                {meta.length > 0 && <Text style={styles.meta}>{meta.join(' · ')}</Text>}
                {s.exists && (
                  <View style={styles.warn}>
                    <Icon icon={faTriangleExclamation} size={11} color={t.kind.image[1]} />
                    <Text style={[styles.warnText, {color: t.kind.image[1]}]}>{tr('skill_install_exists')}</Text>
                  </View>
                )}
              </View>
            </Pressable>
          );
        })}
      </ScrollView>
      {!!error && <Text style={styles.error}>{error}</Text>}
      <View style={styles.actions}>
        <ActionButton label={tr('common_cancel')} disabled={busy} onPress={onClose} style={styles.flex} />
        <ActionButton
          label={multi ? trf('skill_install_n', {n: selected.size}) : tr('skill_install')}
          tone="primary"
          loading={busy}
          disabled={!selected.size}
          onPress={install}
          style={styles.flex}
        />
      </View>
    </Sheet>
  );
}

const useStyles = makeStyles(t => ({
  list: {maxHeight: 360},
  listBody: {paddingHorizontal: 12, gap: 8},
  item: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
    padding: 12,
    borderRadius: radius.md,
    backgroundColor: t.bg1,
    borderWidth: 1,
    borderColor: t.line1,
  },
  itemOn: {borderColor: t.accentLine},
  check: {
    width: 18,
    height: 18,
    marginTop: 1,
    borderRadius: 5,
    borderWidth: 1.5,
    borderColor: t.line2,
    alignItems: 'center',
    justifyContent: 'center',
  },
  checkOn: {backgroundColor: t.accent, borderColor: t.accent},
  text: {flex: 1, minWidth: 0},
  name: {fontSize: 15, fontWeight: '600', color: t.t1},
  desc: {fontSize: 13, lineHeight: 19, color: t.t2, marginTop: 4},
  meta: {fontSize: 12, color: t.t3, marginTop: 6, fontVariant: ['tabular-nums']},
  warn: {flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 6},
  warnText: {fontSize: 12},
  error: {fontSize: 12, lineHeight: 18, color: t.danger, paddingHorizontal: 12, paddingTop: 10},
  actions: {flexDirection: 'row', gap: 10, paddingHorizontal: 12, paddingTop: 14, paddingBottom: 4},
  flex: {flex: 1},
}));
