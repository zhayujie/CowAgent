import React, {useState} from 'react';
import {
  ActivityIndicator,
  Image,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  Text,
  TextInput,
} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {isPublicCleartext} from '../api/http';
import logo from '../assets/logo-mark.png';
import {tr, trf} from '../i18n';
import {isLocalKernelAvailable, LOCAL_SERVER_ID} from '../kernel/localKernel';
import {activeServer, describeConnectError, useServerStore} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';

export function LoginScreen() {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const connect = useServerStore(s => s.connect);
  const returnTo = useServerStore(s => s.returnTo);
  const returnHost = useServerStore(s => s.servers.find(p => p.id === s.returnTo)?.baseUrl);
  const returnLabel =
    returnTo === LOCAL_SERVER_ID ? tr('server_local') : returnHost?.replace(/^https?:\/\//, '');
  const [url, setUrl] = useState(() => activeServer()?.baseUrl ?? '');
  const [password, setPassword] = useState('');
  const [focus, setFocus] = useState<'url' | 'password' | null>(null);
  const [busy, setBusy] = useState(false);
  // Sign-ins that need no form input: the built-in agent, or going back to the server left.
  const [pending, setPending] = useState<'local' | 'back' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const disabled = busy || !!pending || !url || !password;

  const submit = async () => {
    if (disabled) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await connect(url, password);
    } catch (e) {
      setError(describeConnectError(e));
    } finally {
      setBusy(false);
    }
  };

  const switchTo = async (kind: 'local' | 'back', id: string) => {
    if (busy || pending) {
      return;
    }
    setPending(kind);
    setError(null);
    try {
      await useServerStore.getState().switchTo(id);
    } catch (e) {
      setError(describeConnectError(e));
    } finally {
      setPending(null);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.root}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView
        contentContainerStyle={[styles.body, {paddingTop: insets.top + 56, paddingBottom: insets.bottom + 32}]}
        keyboardShouldPersistTaps="handled">
        <Image source={logo} style={styles.logo} />
        <Text style={styles.eyebrow}>COWAGENT</Text>
        <Text style={styles.title}>{tr('login_heading')}</Text>
        <Text style={styles.lead}>
          {isLocalKernelAvailable() ? tr('login_lead_local') : tr('login_lead')}
        </Text>

        {isLocalKernelAvailable() && (
          <>
            <Pressable
              accessibilityRole="button"
              disabled={busy || !!pending}
              onPress={() => switchTo('local', LOCAL_SERVER_ID)}
              style={({pressed}) => [styles.button, styles.localButton, pressed && styles.buttonPressed]}>
              {pending === 'local' ? (
                <ActivityIndicator color={t.onAccent} />
              ) : (
                <Text style={styles.buttonText}>{tr('login_run_local')}</Text>
              )}
            </Pressable>
            <Text style={styles.footnote}>{tr('login_local_footnote')}</Text>
            <Text style={styles.divider}>{tr('login_or_server')}</Text>
          </>
        )}

        <Text style={styles.label}>{tr('login_server_url')}</Text>
        <TextInput
          style={[styles.input, focus === 'url' && styles.inputFocused]}
          value={url}
          onChangeText={setUrl}
          onFocus={() => setFocus('url')}
          onBlur={() => setFocus(null)}
          placeholder="https://cow.example.com"
          placeholderTextColor={t.t4}
          selectionColor={t.accent}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          returnKeyType="next"
        />
        {isPublicCleartext(url) && (
          <Text style={styles.warning}>{tr('login_cleartext_warning')}</Text>
        )}
        <Text style={styles.label}>{tr('login_password')}</Text>
        <TextInput
          style={[styles.input, focus === 'password' && styles.inputFocused]}
          value={password}
          onChangeText={setPassword}
          onFocus={() => setFocus('password')}
          onBlur={() => setFocus(null)}
          placeholder={tr('login_password_placeholder')}
          placeholderTextColor={t.t4}
          selectionColor={t.accent}
          secureTextEntry
          returnKeyType="go"
          onSubmitEditing={submit}
        />
        {!!error && <Text style={styles.error}>{error}</Text>}
        <Pressable
          accessibilityRole="button"
          disabled={disabled}
          onPress={submit}
          style={({pressed}) => [styles.button, disabled && styles.buttonOff, pressed && styles.buttonPressed]}>
          {busy ? (
            <ActivityIndicator color={t.onAccent} />
          ) : (
            <Text style={[styles.buttonText, disabled && styles.buttonTextOff]}>{tr('login_connect')}</Text>
          )}
        </Pressable>
        <Text style={styles.footnote}>{tr('login_footnote')}</Text>
        {!!returnTo && !!returnLabel && (
          <Pressable
            accessibilityRole="button"
            hitSlop={8}
            disabled={busy || !!pending}
            onPress={() => switchTo('back', returnTo)}>
            <Text style={styles.back}>{pending === 'back' ? tr('login_going_back') : trf('login_back_to', {name: returnLabel})}</Text>
          </Pressable>
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  body: {paddingHorizontal: 24},
  logo: {width: 44, height: 44, marginBottom: 28},
  eyebrow: {fontSize: 11, fontWeight: '600', letterSpacing: 1.8, color: t.accent, marginBottom: 10},
  title: {fontSize: 26, lineHeight: 34, fontWeight: '600', letterSpacing: -0.7, color: t.t1},
  lead: {fontSize: 14, lineHeight: 22, color: t.t2, marginTop: 8, marginBottom: 30},
  label: {fontSize: 12, color: t.t3, marginBottom: 8, marginTop: 4, letterSpacing: 0.2},
  input: {
    height: 48,
    marginBottom: 14,
    paddingHorizontal: 14,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: t.line2,
    backgroundColor: t.bg2,
    color: t.t1,
    fontSize: 15,
  },
  inputFocused: {borderColor: t.accentLine},
  warning: {fontSize: 12, lineHeight: 18, color: t.danger, marginTop: -6, marginBottom: 12},
  error: {
    fontSize: 13,
    lineHeight: 19,
    color: t.danger,
    backgroundColor: t.dangerSoft,
    paddingHorizontal: 12,
    paddingVertical: 9,
    borderRadius: radius.sm,
    overflow: 'hidden',
    marginTop: 2,
  },
  button: {
    height: 48,
    marginTop: 18,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.green,
  },
  localButton: {marginTop: 0},
  divider: {fontSize: 12, color: t.t3, marginTop: 30, marginBottom: 14, letterSpacing: 0.2},
  buttonOff: {backgroundColor: t.bg3},
  buttonPressed: {backgroundColor: t.greenDeep},
  buttonText: {fontSize: 16, fontWeight: '600', color: t.onAccent},
  buttonTextOff: {color: t.t3},
  footnote: {fontSize: 12, lineHeight: 18, color: t.t4, marginTop: 14},
  back: {fontSize: 14, color: t.accent, marginTop: 28, textAlign: 'center'},
}));
