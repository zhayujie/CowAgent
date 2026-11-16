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
import {activeServer, describeConnectError, useServerStore} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';

export function LoginScreen() {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const connect = useServerStore(s => s.connect);
  const [url, setUrl] = useState(() => activeServer()?.baseUrl ?? '');
  const [password, setPassword] = useState('');
  const [focus, setFocus] = useState<'url' | 'password' | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const disabled = busy || !url || !password;

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

  return (
    <KeyboardAvoidingView
      style={styles.root}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView
        contentContainerStyle={[styles.body, {paddingTop: insets.top + 56, paddingBottom: insets.bottom + 32}]}
        keyboardShouldPersistTaps="handled">
        <Image source={logo} style={styles.logo} />
        <Text style={styles.eyebrow}>COWAGENT</Text>
        <Text style={styles.title}>连接你的 Agent</Text>
        <Text style={styles.lead}>输入部署在服务器或电脑上的 CowAgent 地址，用访问密码登录。</Text>

        <Text style={styles.label}>服务器地址</Text>
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
          <Text style={styles.warning}>这是公网上的 http 地址，密码和登录凭证会明文传输，建议改用 https。</Text>
        )}
        <Text style={styles.label}>访问密码</Text>
        <TextInput
          style={[styles.input, focus === 'password' && styles.inputFocused]}
          value={password}
          onChangeText={setPassword}
          onFocus={() => setFocus('password')}
          onBlur={() => setFocus(null)}
          placeholder="服务端配置的 web_password"
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
            <Text style={[styles.buttonText, disabled && styles.buttonTextOff]}>连接</Text>
          )}
        </Pressable>
        <Text style={styles.footnote}>密码只在这次登录时使用，之后这台设备用独立凭证访问。</Text>
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
  buttonOff: {backgroundColor: t.bg3},
  buttonPressed: {backgroundColor: t.greenDeep},
  buttonText: {fontSize: 16, fontWeight: '600', color: t.onAccent},
  buttonTextOff: {color: t.t3},
  footnote: {fontSize: 12, lineHeight: 18, color: t.t4, marginTop: 14},
}));
