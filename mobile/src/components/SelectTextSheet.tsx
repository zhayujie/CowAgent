import React, {useCallback, useState} from 'react';
import {Platform, ScrollView, Text, TextInput} from 'react-native';
import {tr} from '../i18n';
import {makeStyles, useTheme} from '../theme/theme';
import {Sheet} from './Sheet';

/** A message's text on its own, where any part of it can be selected and copied. */
function SelectTextSheet({text, visible, onClose}: {text: string; visible: boolean; onClose: () => void}) {
  const t = useTheme();
  const styles = useStyles();
  return (
    <Sheet visible={visible} onClose={onClose} title={tr('chat_select_text')}>
      {Platform.OS === 'ios' ? (
        // On iOS only a text view selects part of a text; a Text copies it whole.
        <TextInput
          value={text}
          editable={false}
          multiline
          scrollEnabled
          selectionColor={t.accent}
          style={[styles.text, styles.input]}
        />
      ) : (
        <ScrollView style={styles.scroll}>
          <Text selectable style={[styles.text, styles.plain]}>
            {text}
          </Text>
        </ScrollView>
      )}
    </Sheet>
  );
}

/** Opens a message's text for selecting; the sheet keeps it while sliding away. */
export function useSelectText() {
  const [text, setText] = useState<string | null>(null);
  const [visible, setVisible] = useState(false);
  const open = useCallback((value: string) => {
    setText(value);
    setVisible(true);
  }, []);
  const sheet =
    text === null ? null : <SelectTextSheet text={text} visible={visible} onClose={() => setVisible(false)} />;
  return {open, sheet};
}

const useStyles = makeStyles(t => ({
  text: {fontSize: 15, lineHeight: 24, color: t.t1},
  input: {flexShrink: 1, paddingHorizontal: 12, paddingTop: 0, paddingBottom: 8},
  scroll: {flexGrow: 0, flexShrink: 1},
  plain: {paddingHorizontal: 12, paddingBottom: 8},
}));
