import {
  faCheck,
  faChevronLeft,
  faDesktop,
  faKeyboard,
  faMobileScreen,
  faQrcode,
} from '@fortawesome/free-solid-svg-icons';
import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import React, {useEffect, useRef, useState} from 'react';
import {
  ActivityIndicator,
  BackHandler,
  Image,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {isPublicCleartext} from '../api/http';
import {addressCandidates, parsePairLink, type PairTarget} from '../api/pairing';
import logo from '../assets/logo-mark.png';
import {Icon} from '../components/Icon';
import {usePairAction} from '../components/PairFlow';
import {QrScanner, qrScannerAvailable} from '../components/QrScanner';
import {ChoiceSheet} from '../components/settings';
import {SHEET_DISMISS_MS} from '../components/Sheet';
import {getLang, tr, trf, useLangStore, type Lang} from '../i18n';
import {isLocalKernelAvailable, LOCAL_SERVER_ID, localDeviceName} from '../kernel/localKernel';
import {activeServer, describeConnectError, useServerStore} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';

type Step = 'welcome' | 'manual';
type Where = 'local' | 'remote';
type RemoteWay = 'scan' | 'manual';

/** Each language names itself, so a wrong pick can always be undone. */
const LANGS: {key: Lang; label: string}[] = [
  {key: 'zh', label: '中文'},
  {key: 'en', label: 'EN'},
];

/**
 * First screen whenever no server is signed in: run the built-in agent, or
 * connect a computer by scanning its pairing code or typing its address.
 */
export function LoginScreen() {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const returnTo = useServerStore(s => s.returnTo);
  const returnHost = useServerStore(s => s.servers.find(p => p.id === s.returnTo)?.baseUrl);
  const returnLabel =
    returnTo === LOCAL_SERVER_ID ? localDeviceName() : returnHost?.replace(/^https?:\/\//, '');
  const lang = useLangStore(s => s.lang);
  const local = isLocalKernelAvailable();

  const [step, setStep] = useState<Step>(() => (useServerStore.getState().loginForm ? 'manual' : 'welcome'));
  // Opened straight on the form from the device switcher: back returns to the device in use, not to onboarding.
  const [formOnly] = useState(() => {
    const s = useServerStore.getState();
    return s.loginForm && !!s.returnTo;
  });
  const [where, setWhere] = useState<Where>(local ? 'local' : 'remote');
  const [remoteOpen, setRemoteOpen] = useState(false);
  const [scanning, setScanning] = useState(false);
  // Signed out of a server, or its session ran out: start from its address.
  const [address, setAddress] = useState(() => {
    const server = activeServer();
    return server && !server.local ? server.baseUrl : '';
  });
  const [secret, setSecret] = useState('');
  const [focus, setFocus] = useState<'address' | 'secret' | null>(null);
  // Sign-ins that need no form input: the built-in agent, or going back to the server left.
  const [pending, setPending] = useState<'local' | 'back' | null>(null);
  // A server that stepped aside (e.g. another machine now at its address) says why, once.
  const [formError, setFormError] = useState<string | null>(() => useServerStore.getState().problem);
  useEffect(() => {
    if (useServerStore.getState().problem) {
      useServerStore.setState({problem: null});
    }
  }, []);
  const pairing = usePairAction();
  const busy = pairing.busy || !!pending;
  const error = formError || pairing.error;

  const clearErrors = () => {
    setFormError(null);
    pairing.setError(null);
  };

  const openScanner = () => {
    clearErrors();
    if (qrScannerAvailable) {
      setScanning(true);
    } else {
      setStep('manual');
    }
  };

  const onScanned = (target: PairTarget) => {
    setScanning(false);
    pairing.run(target);
  };

  const toManual = () => {
    setScanning(false);
    clearErrors();
    // iOS can't push the next screen while the camera modal is still closing.
    setTimeout(() => setStep('manual'), scanning ? SHEET_DISMISS_MS : 0);
  };

  const switchTo = async (kind: 'local' | 'back', id: string) => {
    if (busy) {
      return;
    }
    setPending(kind);
    clearErrors();
    try {
      await useServerStore.getState().switchTo(id);
    } catch (e) {
      setFormError(describeConnectError(e));
    } finally {
      setPending(null);
    }
  };

  const go = (target: Where) => {
    if (busy) {
      return;
    }
    setWhere(target);
    if (target === 'local') {
      switchTo('local', LOCAL_SERVER_ID);
      return;
    }
    clearErrors();
    if (qrScannerAvailable) {
      setRemoteOpen(true);
    } else {
      toManual();
    }
  };

  const onRemoteWay = (way: RemoteWay) => {
    setRemoteOpen(false);
    // The scanner is a modal too, and iOS can't open one while another closes.
    setTimeout(() => (way === 'scan' ? openScanner() : toManual()), SHEET_DISMISS_MS);
  };

  /** Returns whether there was somewhere to go, so the system back gesture otherwise leaves the app. */
  const back = (): boolean => {
    if (busy) {
      return true;
    }
    clearErrors();
    if (step === 'manual' && !formOnly) {
      setStep('welcome');
      return true;
    }
    if (returnTo) {
      switchTo('back', returnTo);
      return true;
    }
    if (step === 'manual') {
      setStep('welcome');
      return true;
    }
    return false;
  };
  const backRef = useRef(back);
  backRef.current = back;
  useEffect(() => {
    const sub = BackHandler.addEventListener('hardwareBackPress', () => backRef.current());
    return () => sub.remove();
  }, []);

  const pastedLink = parsePairLink(address);
  const submitDisabled = busy || !address.trim() || (!secret.trim() && !pastedLink);
  const submit = async () => {
    if (submitDisabled) {
      return;
    }
    clearErrors();
    if (pastedLink) {
      await pairing.run(pastedLink);
      return;
    }
    await pairing.run({code: secret.trim(), urls: addressCandidates(address)});
  };

  const langSwitch = (
    <View style={styles.langs}>
      {LANGS.map(l => {
        const active = (lang ?? getLang()) === l.key;
        return (
          <Pressable
            key={l.key}
            accessibilityRole="radio"
            accessibilityState={{selected: active}}
            onPress={() => useLangStore.getState().setLang(l.key)}
            style={[styles.lang, active && styles.langActive]}>
            <Text style={[styles.langText, active && styles.langTextActive]}>{l.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );

  const errorBox = !!error && <Text style={styles.error}>{error}</Text>;

  const backLink = !!returnTo && !!returnLabel && (
    <Pressable accessibilityRole="button" hitSlop={8} disabled={busy} onPress={() => switchTo('back', returnTo)}>
      <Text style={styles.back}>
        {pending === 'back' ? tr('login_going_back') : trf('login_back_to', {name: returnLabel})}
      </Text>
    </Pressable>
  );

  return (
    <KeyboardAvoidingView style={styles.root} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView
        contentContainerStyle={[styles.body, {paddingTop: insets.top + 12, paddingBottom: insets.bottom + 32}]}
        keyboardShouldPersistTaps="handled">
        <View style={styles.topBar}>
          {step === 'manual' ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={tr('common_back')}
              hitSlop={10}
              disabled={busy}
              onPress={back}
              style={styles.backButton}>
              <Icon icon={faChevronLeft} size={16} color={t.t2} />
            </Pressable>
          ) : (
            <View />
          )}
          {langSwitch}
        </View>

        {step === 'welcome' ? (
          <>
            <Image source={logo} style={styles.logo} />
            <Text style={styles.eyebrow}>COWAGENT</Text>
            <Text style={styles.title}>{tr('connect_welcome_title')}</Text>
            <Text style={styles.lead}>{local ? tr('connect_welcome_lead') : tr('connect_welcome_lead_remote')}</Text>

            {errorBox}

            {local && (
              <Choice
                icon={faMobileScreen}
                title={tr('connect_local_title')}
                desc={tr('connect_local_desc')}
                selected={where === 'local'}
                busy={pending === 'local'}
                disabled={busy}
                onPress={() => go('local')}
              />
            )}
            <Choice
              icon={faDesktop}
              title={tr('connect_pc_title')}
              desc={tr('connect_pc_desc')}
              selected={where === 'remote'}
              busy={pairing.busy}
              disabled={busy}
              onPress={() => go('remote')}
            />

            <View style={styles.spacer} />
            <Pressable
              accessibilityRole="button"
              disabled={busy}
              onPress={() => go(where)}
              style={({pressed}) => [styles.button, styles.nextButton, pressed && styles.buttonPressed]}>
              {pending === 'local' || pairing.busy ? (
                <ActivityIndicator color={t.onAccent} />
              ) : (
                <Text style={styles.buttonText}>{tr('connect_next')}</Text>
              )}
            </Pressable>
            {backLink}
          </>
        ) : (
          <>
            <Text style={[styles.title, styles.titleManual]}>{tr('connect_manual_title')}</Text>
            <Text style={styles.lead}>{tr('connect_manual_lead')}</Text>

            <Text style={styles.label}>{tr('connect_address')}</Text>
            <TextInput
              style={[styles.input, focus === 'address' && styles.inputFocused]}
              value={address}
              onChangeText={setAddress}
              onFocus={() => setFocus('address')}
              onBlur={() => setFocus(null)}
              placeholder={tr('connect_address_placeholder')}
              placeholderTextColor={t.t4}
              selectionColor={t.accent}
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="url"
              returnKeyType="next"
            />
            {!pastedLink && addressCandidates(address).every(isPublicCleartext) && !!address.trim() && (
              <Text style={styles.warning}>{tr('login_cleartext_warning')}</Text>
            )}
            <Text style={styles.label}>{tr('connect_code')}</Text>
            <TextInput
              style={[styles.input, styles.codeInput, focus === 'secret' && styles.inputFocused]}
              value={secret}
              onChangeText={setSecret}
              onFocus={() => setFocus('secret')}
              onBlur={() => setFocus(null)}
              placeholder={tr('connect_code_placeholder')}
              placeholderTextColor={t.t4}
              selectionColor={t.accent}
              autoCapitalize="characters"
              autoCorrect={false}
              maxLength={12}
              returnKeyType="go"
              onSubmitEditing={submit}
            />
            {errorBox}
            <Pressable
              accessibilityRole="button"
              disabled={submitDisabled}
              onPress={submit}
              style={({pressed}) => [styles.button, submitDisabled && styles.buttonOff, pressed && styles.buttonPressed]}>
              {pairing.busy ? (
                <ActivityIndicator color={t.onAccent} />
              ) : (
                <Text style={[styles.buttonText, submitDisabled && styles.buttonTextOff]}>{tr('connect_submit')}</Text>
              )}
            </Pressable>
            <Text style={styles.footnote}>{tr('connect_code_footnote')}</Text>
            {backLink}
          </>
        )}
      </ScrollView>

      <ChoiceSheet<RemoteWay>
        visible={remoteOpen}
        title={tr('connect_pc_title')}
        options={[
          {key: 'scan', label: tr('connect_scan'), desc: tr('connect_scan_desc'), icon: faQrcode},
          {key: 'manual', label: tr('connect_manual'), desc: tr('connect_manual_desc'), icon: faKeyboard},
        ]}
        note={tr('connect_remote_note')}
        onSelect={onRemoteWay}
        onClose={() => setRemoteOpen(false)}
      />
      <QrScanner visible={scanning} onClose={() => setScanning(false)} onScanned={onScanned} onManual={toManual} />
    </KeyboardAvoidingView>
  );
}

/** One of the places the Agent can run; tapping it also moves on, like Next. */
function Choice({
  icon,
  title,
  desc,
  selected,
  busy,
  disabled,
  onPress,
}: {
  icon: IconDefinition;
  title: string;
  desc: string;
  selected: boolean;
  busy?: boolean;
  disabled?: boolean;
  onPress: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{selected, busy, disabled}}
      disabled={disabled}
      onPress={onPress}
      style={({pressed}) => [styles.choice, selected && styles.choiceSelected, pressed && styles.choicePressed]}>
      <View style={[styles.choiceIcon, selected && styles.choiceIconSelected]}>
        <Icon icon={icon} size={18} color={selected ? t.onAccent : t.t2} />
      </View>
      <View style={styles.choiceText}>
        <Text style={styles.choiceTitle}>{title}</Text>
        <Text style={styles.choiceDesc} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.85}>
          {desc}
        </Text>
      </View>
      {busy ? (
        <ActivityIndicator color={t.t3} />
      ) : (
        <View style={[styles.radio, selected && styles.radioOn]}>
          {selected && <Icon icon={faCheck} size={10} color={t.onAccent} />}
        </View>
      )}
    </Pressable>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  body: {flexGrow: 1, paddingHorizontal: 24},
  topBar: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 36, minHeight: 34},
  backButton: {width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center', backgroundColor: t.bg2},
  langs: {flexDirection: 'row', padding: 3, borderRadius: 999, backgroundColor: t.bg2},
  lang: {paddingHorizontal: 11, paddingVertical: 5, borderRadius: 999},
  langActive: {backgroundColor: t.isDark ? t.bg3 : t.bg0},
  langText: {fontSize: 12, color: t.t3, fontWeight: '500'},
  langTextActive: {color: t.t1, fontWeight: '600'},
  logo: {width: 48, height: 48, marginBottom: 24},
  eyebrow: {fontSize: 11, fontWeight: '600', letterSpacing: 1.8, color: t.accent, marginBottom: 10},
  title: {fontSize: 26, lineHeight: 34, fontWeight: '600', letterSpacing: -0.7, color: t.t1},
  titleManual: {marginTop: 4},
  lead: {fontSize: 14, lineHeight: 22, color: t.t2, marginTop: 8, marginBottom: 28},
  choice: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 14,
    paddingVertical: 20,
    marginBottom: 14,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: t.line2,
    backgroundColor: t.bg1,
  },
  choiceSelected: {borderColor: t.accentLine, backgroundColor: t.accentSoft},
  choicePressed: {opacity: 0.75},
  choiceIcon: {
    width: 44,
    height: 44,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.bg3,
  },
  choiceIconSelected: {backgroundColor: t.green},
  choiceText: {flex: 1},
  choiceTitle: {fontSize: 16, fontWeight: '600', color: t.t1, letterSpacing: -0.2},
  choiceDesc: {fontSize: 13, lineHeight: 19, color: t.t3, marginTop: 3},
  radio: {
    width: 20,
    height: 20,
    borderRadius: 10,
    borderWidth: 1.5,
    borderColor: t.line2,
    alignItems: 'center',
    justifyContent: 'center',
  },
  radioOn: {borderColor: t.green, backgroundColor: t.green},
  spacer: {flexGrow: 1, minHeight: 24},
  nextButton: {marginTop: 0},
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
  codeInput: {fontSize: 18, letterSpacing: 3, fontWeight: '600'},
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
    marginBottom: 14,
  },
  button: {
    height: 48,
    marginTop: 4,
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
  back: {fontSize: 14, color: t.accent, marginTop: 28, textAlign: 'center'},
}));
