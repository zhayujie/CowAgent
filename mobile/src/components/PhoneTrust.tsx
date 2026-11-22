import {faShieldHalved} from '@fortawesome/free-solid-svg-icons';
import React, {useState} from 'react';
import {Pressable, Text, View} from 'react-native';
import {tr} from '../i18n';
import {LOCAL_SERVER_ID} from '../kernel/localKernel';
import {trustScope} from '../phone/handlers';
import {setTrusted, usePhonePrompts} from '../phone/prompts';
import {useServerStore} from '../store/serverStore';
import {makeStyles, useTheme} from '../theme/theme';
import {Icon} from './Icon';

/** Under a phone tool's call the user said to always allow: the way back to being asked. */
export function PhoneTrust({tool, args}: {tool: string; args?: Record<string, unknown>}) {
  const t = useTheme();
  const styles = useStyles();
  const local = useServerStore(s => s.activeId === LOCAL_SERVER_ID);
  const scope = local ? trustScope(tool, args) : null;
  const trusted = usePhonePrompts(s => !!scope && s.trusted.includes(scope));
  const [revoked, setRevoked] = useState(false);
  if (!scope || (!trusted && !revoked)) {
    return null;
  }
  return (
    <View style={styles.row}>
      <Icon icon={faShieldHalved} size={11} color={t.t4} />
      <Text style={styles.note}>{tr(trusted ? 'phone_trusted_note' : 'phone_trusted_revoked')}</Text>
      {trusted && (
        <Pressable
          accessibilityRole="button"
          hitSlop={8}
          onPress={() => {
            setTrusted(scope, false);
            setRevoked(true);
          }}>
          <Text style={styles.action}>{tr('phone_trusted_revoke')}</Text>
        </Pressable>
      )}
    </View>
  );
}

const useStyles = makeStyles(t => ({
  row: {flexDirection: 'row', alignItems: 'center', gap: 6, paddingVertical: 2},
  note: {fontSize: 12, color: t.t3},
  action: {fontSize: 12, fontWeight: '600', color: t.accent},
}));
