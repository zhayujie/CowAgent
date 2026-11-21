import {faCopy} from '@fortawesome/free-regular-svg-icons';
import React, {Fragment, memo, useEffect, useMemo, useState, type ReactNode} from 'react';
import {
  Image,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
  type ImageStyle,
  type TextStyle,
  type ViewStyle,
} from 'react-native';
import {Renderer, useMarkdown, type MarkedStyles} from 'react-native-marked';
import {
  type ChatFile,
  codeFilePath,
  fileBaseName,
  fileFromImageRef,
  rawUrlOf,
  splitFilePaths,
} from '../files/chatFile';
import {openFileRef, openLink, useImageViewer} from '../files/openFile';
import {tr, trf} from '../i18n';
import type {Palette} from '../theme/palette';
import {useTheme} from '../theme/theme';
import {languageOf} from '../utils/highlight';
import {copyText} from '../utils/clipboard';
import {CodeText} from './CodeText';
import {FileSheet} from './FileViews';
import {Icon} from './Icon';
import {showToast} from './Toast';

const MONO = Platform.select({ios: 'Menlo', default: 'monospace'});
// Web preview renders inside a phone-sized frame (see web/index.html).
const MAX_FRAME_WIDTH = Platform.OS === 'web' ? 430 : Number.POSITIVE_INFINITY;
// Horizontal padding of the message column (and the scrollbar on web).
const COLUMN_INSET = 18 * 2;
const MIN_COL_WIDTH = 110;
const INLINE_BOX_PAD = 5;

/** Rough width of a monospace run: wide (CJK) glyphs take about twice a narrow one. */
function monoWidth(text: string, fontSize: number): number {
  let width = 0;
  for (const ch of text) {
    width += /[\u1100-\uffef]/.test(ch) ? fontSize : fontSize * 0.62;
  }
  return width;
}

// The stock renderer sizes every column at ~43% of the window width, which hides
// most columns off-screen; fit columns to the message column and scroll only when needed.
class ChatRenderer extends Renderer {
  constructor(
    private contentWidth: number,
    private t: Palette,
    private onLink?: (href: string) => boolean,
  ) {
    super();
  }

  private follow(href: string) {
    if (!this.onLink?.(href)) {
      openLink(href);
    }
  }

  text(text: string | ReactNode[], textStyle?: TextStyle): ReactNode {
    const parts = typeof text === 'string' ? splitFilePaths(text) : null;
    if (!parts) {
      return super.text(text, textStyle);
    }
    const {t} = this;
    return (
      <Text key={this.getKey()} selectable style={textStyle}>
        {parts.map((p, i) =>
          typeof p === 'string' ? (
            p
          ) : (
            <Text
              key={`f${i}`}
              accessibilityRole="link"
              accessibilityLabel={trf('file_open_named', {path: p.path})}
              onPress={() => openFileRef(p.path)}
              style={[styles.fileChip, {color: t.accent}]}>
              {fileBaseName(p.path)}
            </Text>
          ),
        )}
      </Text>
    );
  }

  code(text: string, language?: string, containerStyle?: ViewStyle, textStyle?: TextStyle): ReactNode {
    return (
      <CodeBlock key={this.getKey()} code={text} language={language} boxStyle={containerStyle} textStyle={textStyle} />
    );
  }

  codespan(text: string, codeStyle?: TextStyle): ReactNode {
    const path = codeFilePath(text);
    // Text spans can only paint square tints, so the tint goes on a rounded box or not at all.
    const {backgroundColor, ...glyphs} = StyleSheet.flatten(codeStyle) ?? {};
    if (!path) {
      // Android rests an inline box on the baseline; the nudge puts its text back on the line.
      const fits =
        !text.includes('\n') && monoWidth(text, glyphs.fontSize ?? 13) + INLINE_BOX_PAD * 2 <= this.contentWidth;
      if (fits) {
        return (
          <View key={this.getKey()} style={[styles.inlineCode, {backgroundColor, maxWidth: this.contentWidth}]}>
            <Text style={[glyphs, styles.inlineCodeText]}>{text}</Text>
          </View>
        );
      }
      // A box cannot wrap, so code longer than a line keeps only its typeface and colour.
      return (
        <Text key={this.getKey()} selectable style={glyphs}>
          {text}
        </Text>
      );
    }
    return (
      <Text
        key={this.getKey()}
        selectable
        accessibilityRole="link"
        accessibilityLabel={trf('file_open_named', {path})}
        onPress={() => openFileRef(path)}
        style={[glyphs, styles.codeLink, {color: this.t.accent}]}>
        {text}
      </Text>
    );
  }

  link(children: string | ReactNode[], href: string, linkStyle?: TextStyle): ReactNode {
    return (
      <Text
        key={this.getKey()}
        selectable
        accessibilityRole="link"
        onPress={() => this.follow(href)}
        style={linkStyle}>
        {children}
      </Text>
    );
  }

  image(uri: string, alt?: string, style?: ImageStyle, title?: string): ReactNode {
    if (/\.svg$/i.test(uri.replace(/[?#].*/, ''))) {
      return super.image(uri, alt, style, title);
    }
    return <ReplyImage key={this.getKey()} file={fileFromImageRef(uri, alt)} maxWidth={this.contentWidth} />;
  }

  linkImage(href: string, imageUrl: string, alt?: string): ReactNode {
    return (
      <Pressable key={this.getKey()} accessibilityRole="link" onPress={() => this.follow(href)}>
        <ReplyImage file={fileFromImageRef(imageUrl, alt)} maxWidth={this.contentWidth} />
      </Pressable>
    );
  }

  table(
    header: ReactNode[][],
    rows: ReactNode[][][],
    tableStyle?: ViewStyle,
    rowStyle?: ViewStyle,
    cellStyle?: ViewStyle,
  ): ReactNode {
    const {t} = this;
    const cols = Math.max(header.length, 1);
    const colWidth = Math.max(MIN_COL_WIDTH, Math.floor((this.contentWidth - 2) / cols));
    const renderRow = (cells: ReactNode[][], key: string, isHeader: boolean) => (
      <View
        key={key}
        style={[
          rowStyle,
          isHeader ? {backgroundColor: t.bg1} : [styles.rowDivider, {borderTopColor: t.line1}],
        ]}>
        {cells.map((cell, i) => (
          <View
            key={`c${i}`}
            style={[
              cellStyle,
              {width: colWidth},
              i > 0 && [styles.colDivider, {borderLeftColor: t.line1}],
            ]}>
            {cell}
          </View>
        ))}
      </View>
    );
    return (
      <ScrollView key={this.getKey()} horizontal showsHorizontalScrollIndicator={false}>
        <View style={tableStyle}>
          {renderRow(header, 'h', true)}
          {rows.map((row, i) => renderRow(row, `r${i}`, false))}
        </View>
      </ScrollView>
    );
  }
}

function buildStyles(t: Palette): MarkedStyles {
  const base = {fontSize: 15, lineHeight: 24.5, color: t.t1} as const;
  const heading = {color: t.t1, fontWeight: '600', letterSpacing: -0.3} as const;
  return {
    text: base,
    paragraph: {paddingVertical: 4},
    strong: {...base, fontWeight: '600'},
    em: {...base, fontStyle: 'italic'},
    strikethrough: {...base, textDecorationLine: 'line-through', color: t.t2},
    link: {...base, color: t.accent, fontStyle: 'normal', textDecorationLine: 'underline'},
    h1: {...heading, fontSize: 20, lineHeight: 28, marginTop: 12, marginBottom: 4, paddingBottom: 0, borderBottomWidth: 0},
    h2: {...heading, fontSize: 18, lineHeight: 26, marginTop: 12, marginBottom: 4, paddingBottom: 0, borderBottomWidth: 0},
    h3: {...heading, fontSize: 16.5, lineHeight: 24, marginTop: 10, marginBottom: 2},
    h4: {...heading, fontSize: 15, lineHeight: 23, marginTop: 8, marginBottom: 2},
    h5: {...heading, fontSize: 15, lineHeight: 23},
    h6: {...heading, fontSize: 14, lineHeight: 21, color: t.t2},
    codespan: {
      fontFamily: MONO,
      fontSize: 13,
      fontStyle: 'normal',
      fontWeight: '400',
      color: t.inlineCodeText,
      backgroundColor: t.inlineCodeBg,
    },
    code: {
      marginVertical: 8,
      borderRadius: 12,
      backgroundColor: t.codeBg,
      borderWidth: 1,
      borderColor: t.line1,
    },
    codeText: {fontFamily: MONO, fontSize: 12.5, lineHeight: 19, color: t.t1},
    blockquote: {
      marginVertical: 6,
      paddingLeft: 12,
      paddingVertical: 2,
      borderLeftWidth: 2,
      borderLeftColor: t.green,
      opacity: 1,
    },
    hr: {marginVertical: 14, borderBottomWidth: 1, borderBottomColor: t.line1},
    list: {marginVertical: 2},
    li: base,
    table: {
      marginVertical: 8,
      borderWidth: 1,
      borderColor: t.line2,
      borderRadius: 10,
      overflow: 'hidden',
    },
    tableCell: {paddingVertical: 7, paddingHorizontal: 10},
    image: {borderRadius: 10},
  };
}

/** Smaller and quieter, for text inside a reply's process timeline. */
function buildCompactStyles(t: Palette): MarkedStyles {
  const full = buildStyles(t);
  const base = {fontSize: 12.5, lineHeight: 19.5, color: t.t2} as const;
  const heading = {...base, color: t.t1, fontWeight: '600', marginTop: 6, marginBottom: 2} as const;
  return {
    ...full,
    text: base,
    paragraph: {paddingVertical: 2},
    strong: {...base, fontWeight: '600'},
    em: {...base, fontStyle: 'italic'},
    strikethrough: {...base, textDecorationLine: 'line-through'},
    link: {...base, color: t.accent, fontStyle: 'normal', textDecorationLine: 'underline'},
    li: base,
    h1: {...heading, fontSize: 14, lineHeight: 21, paddingBottom: 0, borderBottomWidth: 0},
    h2: {...heading, fontSize: 13.5, lineHeight: 20, paddingBottom: 0, borderBottomWidth: 0},
    h3: {...heading, fontSize: 13, lineHeight: 20},
    h4: heading,
    h5: heading,
    h6: heading,
    codespan: {...full.codespan, fontSize: 11.5},
    code: {...full.code, marginVertical: 4},
    codeText: {...full.codeText, fontSize: 11.5, lineHeight: 17},
  };
}

function buildTheme(t: Palette) {
  return {colors: {text: t.t1, link: t.accent, code: t.codeBg, border: t.line2}};
}

type Cached = {styles: MarkedStyles; theme: ReturnType<typeof buildTheme>};
const styleCache = new Map<Palette, Cached>();
const compactCache = new Map<Palette, Cached>();

function MarkdownImpl({
  value,
  compact,
  inset = COLUMN_INSET,
  onLink,
}: {
  value: string;
  compact?: boolean;
  /** Horizontal space around the text, so tables can size their columns to fit. */
  inset?: number;
  /** Gets first say on a tapped link; returning true keeps it from opening externally. */
  onLink?: (href: string) => boolean;
}) {
  const t = useTheme();
  const {width} = useWindowDimensions();
  const contentWidth = Math.min(width, MAX_FRAME_WIDTH) - inset;
  const cache = compact ? compactCache : styleCache;
  let cached = cache.get(t);
  if (!cached) {
    cached = {styles: compact ? buildCompactStyles(t) : buildStyles(t), theme: buildTheme(t)};
    cache.set(t, cached);
  }
  // Element keys come from a counter that never resets, so a renderer reused
  // across streamed updates would give every element a new key and remount it.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const renderer = useMemo(() => new ChatRenderer(contentWidth, t, onLink), [contentWidth, t, value, onLink]);
  const elements = useMarkdown(value, {
    styles: cached.styles,
    theme: cached.theme,
    colorScheme: t.isDark ? 'dark' : 'light',
    renderer,
  });
  return (
    <View style={styles.root}>
      {elements.map((element, index) => (
        <Fragment key={`md-${index}`}>{element}</Fragment>
      ))}
    </View>
  );
}

export const Markdown = memo(MarkdownImpl);

/** A fenced block: its language and a copy button over the code, which scrolls sideways on its own. */
function CodeBlock({
  code,
  language,
  boxStyle,
  textStyle,
}: {
  code: string;
  language?: string;
  boxStyle?: ViewStyle;
  textStyle?: TextStyle;
}) {
  const t = useTheme();
  const lang = languageOf(language);
  const copy = () => copyText(code).then(ok => ok && showToast(tr('common_copied')));
  return (
    <View style={[boxStyle, styles.codeBox]}>
      <View style={styles.codeHead}>
        <Text style={[styles.codeLang, {color: t.t3}]} numberOfLines={1}>
          {language?.trim() || lang || 'text'}
        </Text>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={tr('common_copy')}
          hitSlop={8}
          onPress={copy}
          style={({pressed}) => [styles.codeCopy, pressed && styles.pressed]}>
          <Icon icon={faCopy} size={11} color={t.t3} />
          <Text style={[styles.codeCopyText, {color: t.t3}]}>{tr('common_copy')}</Text>
        </Pressable>
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.codeScroll}>
        <CodeText code={code} lang={lang} style={textStyle} />
      </ScrollView>
    </View>
  );
}

const REPLY_IMAGE_MAX_H = 360;

/** A picture inside a reply's text, at its own proportions; a tap shows it full screen, a long press offers the rest. */
function ReplyImage({file, maxWidth}: {file: ChatFile; maxWidth: number}) {
  const t = useTheme();
  const uri = rawUrlOf(file);
  const [size, setSize] = useState<{w: number; h: number} | null>(null);
  const [acting, setActing] = useState(false);
  const [failed, setFailed] = useState(!uri);
  useEffect(() => {
    let alive = true;
    // Kept across streamed updates by position; `done` swaps a relative src for a served one.
    setSize(null);
    setFailed(!uri);
    if (uri) {
      Image.getSize(
        uri,
        (w, h) => alive && w > 0 && h > 0 && setSize({w, h}),
        () => alive && setFailed(true),
      );
    }
    return () => {
      alive = false;
    };
  }, [uri]);
  if (failed) {
    return (
      <Text style={[styles.imageMissing, {color: t.t3}]} numberOfLines={1}>
        {trf('file_image_missing', {name: file.name})}
      </Text>
    );
  }
  let width = Math.min(maxWidth, size?.w ?? maxWidth);
  let height = size ? (width * size.h) / size.w : width * 0.6;
  if (height > REPLY_IMAGE_MAX_H) {
    width = (width * REPLY_IMAGE_MAX_H) / height;
    height = REPLY_IMAGE_MAX_H;
  }
  return (
    <>
      <Pressable
        accessibilityRole="imagebutton"
        accessibilityLabel={trf('file_view_image_named', {name: file.name})}
        accessibilityHint={tr('file_long_press_hint')}
        onPress={() => useImageViewer.getState().show(file)}
        onLongPress={() => setActing(true)}
        delayLongPress={350}
        style={styles.imageWrap}>
        <Image
          source={{uri}}
          style={[styles.image, {width, height, backgroundColor: t.bg2}]}
          resizeMode="contain"
          resizeMethod="resize"
          onError={() => setFailed(true)}
        />
      </Pressable>
      <FileSheet file={file} visible={acting} onClose={() => setActing(false)} />
    </>
  );
}

const styles = StyleSheet.create({
  root: {flexShrink: 1},
  rowDivider: {borderTopWidth: 1},
  colDivider: {borderLeftWidth: 1},
  imageWrap: {alignSelf: 'flex-start', marginVertical: 6},
  image: {borderRadius: 10},
  imageMissing: {fontSize: 12, marginVertical: 4},
  fileChip: {fontWeight: '500', textDecorationLine: 'underline', textDecorationStyle: 'dotted'},
  codeBox: {overflow: 'hidden'},
  inlineCode: {
    paddingHorizontal: INLINE_BOX_PAD,
    paddingVertical: 1,
    borderRadius: 5,
    transform: [{translateY: Platform.OS === 'android' ? 4 : 2}],
  },
  inlineCodeText: {lineHeight: 18},
  codeHead: {flexDirection: 'row', alignItems: 'center', paddingLeft: 12, paddingRight: 8, paddingTop: 7},
  codeLang: {flex: 1, fontSize: 11.5, letterSpacing: 0.3},
  codeCopy: {flexDirection: 'row', alignItems: 'center', gap: 5, paddingHorizontal: 6, paddingVertical: 3},
  codeCopyText: {fontSize: 11.5},
  codeScroll: {paddingHorizontal: 12, paddingTop: 6, paddingBottom: 12},
  pressed: {opacity: 0.55},
  codeLink: {textDecorationLine: 'underline'},
});
