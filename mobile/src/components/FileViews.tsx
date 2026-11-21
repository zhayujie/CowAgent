import {
  faArrowUpRightFromSquare,
  faCopy,
  faDownload,
  faEye,
  faLayerGroup,
  faShareNodes,
} from '@fortawesome/free-solid-svg-icons';
import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import React, {useEffect, useState} from 'react';
import {Image, Pressable, Text, View} from 'react-native';
import {type ChatFile, rawUrlOf} from '../files/chatFile';
import {
  canPreviewInApp,
  downloadFile,
  openFile,
  openInBrowser,
  shareFile,
  useImageViewer,
  viewInArtifacts,
} from '../files/openFile';
import {tr, trf} from '../i18n';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {copyText} from '../utils/clipboard';
import {formatBytes} from '../utils/format';
import {KIND_LABEL, kindGroup, KindTile} from './ArtifactStrip';
import {Icon} from './Icon';
import {ImageViewer} from './ImageViewer';
import {Sheet, SHEET_DISMISS_MS} from './Sheet';
import {showToast} from './Toast';

/** What a tap on the card will do, so the reader knows before tapping. */
function openLabel(f: ChatFile): string {
  return canPreviewInApp(f) ? tr('file_preview') : tr('file_view');
}

function fileSubtitle(f: ChatFile): string {
  return [f.relPath, KIND_LABEL[kindGroup(f.kind)], formatBytes(f.size)].filter(Boolean).join(' · ');
}

/** A file in a reply: tap opens it, the buttons preview / save / locate it, a long press offers the rest. */
export function FileCard({file}: {file: ChatFile}) {
  const styles = useStyles();
  const [acting, setActing] = useState(false);
  return (
    <>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`${openLabel(file)} ${file.name}`}
        accessibilityHint={tr('file_long_press_hint')}
        onPress={() => openFile(file)}
        onLongPress={() => setActing(true)}
        delayLongPress={350}
        style={({pressed}) => [styles.card, pressed && styles.cardPressed]}>
        <KindTile kind={file.kind} previewUrl={file.kind === 'image' ? file.previewUrl : undefined} />
        <View style={styles.cardText}>
          <Text style={styles.cardName} numberOfLines={1} ellipsizeMode="middle">
            {file.name}
          </Text>
          <Text style={styles.cardSub} numberOfLines={1}>
            {fileSubtitle(file)}
          </Text>
        </View>
        <View style={styles.cardActions}>
          {canPreviewInApp(file) && (
            <CardAction icon={faEye} label={trf('file_preview_named', {name: file.name})} onPress={() => openFile(file)} />
          )}
          <CardAction
            icon={faDownload}
            label={trf('file_download_named', {name: file.name})}
            onPress={() => downloadFile(file)}
          />
          {!!file.path && (
            <CardAction
              icon={faLayerGroup}
              label={trf('file_view_in_artifacts_named', {name: file.name})}
              onPress={() => viewInArtifacts(file)}
            />
          )}
        </View>
      </Pressable>
      <FileSheet file={file} visible={acting} onClose={() => setActing(false)} />
    </>
  );
}

function CardAction({icon, label, onPress}: {icon: IconDefinition; label: string; onPress: () => void}) {
  const t = useTheme();
  const styles = useStyles();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      hitSlop={4}
      style={({pressed}) => [styles.cardAction, pressed && styles.cardActionPressed]}>
      <Icon icon={icon} size={12} color={t.t2} />
    </Pressable>
  );
}

const INLINE_MAX_W = 240;
const INLINE_MAX_H = 300;
const INLINE_MIN = 72;

/** A picture a reply sent, shown as itself; falls back to a card when it won't load. */
export function InlineImage({file}: {file: ChatFile}) {
  const styles = useStyles();
  const uri = rawUrlOf(file);
  const [ratio, setRatio] = useState<number | null>(null);
  const [failed, setFailed] = useState(!uri);
  const [acting, setActing] = useState(false);

  useEffect(() => {
    if (!uri) {
      return;
    }
    let alive = true;
    Image.getSize(
      uri,
      (w, h) => alive && w > 0 && h > 0 && setRatio(w / h),
      () => alive && setFailed(true),
    );
    return () => {
      alive = false;
    };
  }, [uri]);

  if (failed) {
    return <FileCard file={file} />;
  }
  let width = INLINE_MAX_W;
  let height = ratio ? width / ratio : INLINE_MAX_W * 0.62;
  if (height > INLINE_MAX_H) {
    height = INLINE_MAX_H;
    width = Math.max(INLINE_MIN, height * (ratio ?? 1));
  }
  height = Math.max(INLINE_MIN, height);
  return (
    <>
      <Pressable
        accessibilityRole="imagebutton"
        accessibilityLabel={trf('file_view_image_named', {name: file.name})}
        accessibilityHint={tr('file_long_press_hint')}
        onPress={() => useImageViewer.getState().show(file)}
        onLongPress={() => setActing(true)}
        delayLongPress={350}
        style={({pressed}) => [styles.inline, pressed && styles.inlinePressed]}>
        <Image
          source={{uri}}
          style={[styles.inlineImage, {width, height}]}
          resizeMode="cover"
          resizeMethod="resize"
          onError={() => setFailed(true)}
        />
      </Pressable>
      <FileSheet file={file} visible={acting} onClose={() => setActing(false)} />
    </>
  );
}

/** Everything one can do with a file, for the long press. */
export function FileSheet({
  file,
  visible,
  onClose,
  inPreview,
}: {
  file: ChatFile;
  visible: boolean;
  onClose: () => void;
  /** Opened from the preview itself, so previewing again would go nowhere. */
  inPreview?: boolean;
}) {
  const then = (fn: () => void) => () => {
    onClose();
    setTimeout(fn, SHEET_DISMISS_MS);
  };
  const copy = async () => {
    const ok = await copyText(file.path ?? file.relPath ?? file.name);
    showToast(ok ? tr('file_path_copied') : tr('file_copy_failed'));
  };
  return (
    <Sheet visible={visible} onClose={onClose} title={file.name}>
      {!inPreview && canPreviewInApp(file) && (
        <SheetRow icon={faEye} label={tr('file_preview')} onPress={then(() => openFile(file))} />
      )}
      <SheetRow icon={faDownload} label={tr('file_download')} onPress={then(() => downloadFile(file))} />
      <SheetRow icon={faShareNodes} label={tr('file_share')} onPress={then(() => shareFile(file))} />
      <SheetRow
        icon={faArrowUpRightFromSquare}
        label={tr('file_open_external')}
        onPress={then(() => openInBrowser(file))}
      />
      {!!file.path && (
        <SheetRow icon={faLayerGroup} label={tr('file_view_in_artifacts')} onPress={then(() => viewInArtifacts(file))} />
      )}
      {!!(file.path || file.relPath) && <SheetRow icon={faCopy} label={tr('file_copy_path')} onPress={then(copy)} />}
    </Sheet>
  );
}

function SheetRow({icon, label, onPress}: {icon: IconDefinition; label: string; onPress: () => void}) {
  const t = useTheme();
  const styles = useStyles();
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({pressed}) => [styles.sheetRow, pressed && styles.cardPressed]}>
      <View style={styles.sheetIcon}>
        <Icon icon={icon} size={14} color={t.t2} />
      </View>
      <Text style={styles.sheetText}>{label}</Text>
    </Pressable>
  );
}

/** The one full-screen picture any file view can ask for; mount once at the root. */
export function ImageViewerHost() {
  const file = useImageViewer(s => s.file);
  const close = useImageViewer(s => s.close);
  const [acting, setActing] = useState(false);
  useEffect(() => setActing(false), [file]);
  return (
    <ImageViewer
      uri={file ? rawUrlOf(file) : null}
      title={file?.name}
      onClose={close}
      onDownload={file ? () => downloadFile(file) : undefined}
      onOpen={file ? () => openInBrowser(file) : undefined}
      onLongPress={() => setActing(true)}>
      {file && <FileSheet file={file} visible={acting} onClose={() => setActing(false)} inPreview />}
    </ImageViewer>
  );
}

const useStyles = makeStyles(t => ({
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 11,
    paddingVertical: 9,
    paddingLeft: 9,
    paddingRight: 10,
    borderRadius: radius.md,
    backgroundColor: t.isDark ? t.bg2 : t.bg1,
    borderWidth: 1,
    borderColor: t.line1,
  },
  cardPressed: {backgroundColor: t.isDark ? t.bg3 : t.bg2},
  cardText: {flex: 1, minWidth: 0},
  cardName: {fontSize: 13.5, fontWeight: '500', color: t.t1},
  cardSub: {fontSize: 11, color: t.t3, marginTop: 3},
  cardActions: {flexDirection: 'row', gap: 6},
  cardAction: {
    width: 28,
    height: 28,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.isDark ? t.bg1 : t.bg0,
    borderWidth: 1,
    borderColor: t.line1,
  },
  cardActionPressed: {opacity: 0.6},
  inline: {alignSelf: 'flex-start', borderRadius: 10},
  inlinePressed: {opacity: 0.85},
  inlineImage: {borderRadius: 10, backgroundColor: t.bg2, borderWidth: 1, borderColor: t.line1},
  sheetRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 12,
    paddingVertical: 14,
    borderRadius: radius.md,
  },
  sheetIcon: {width: 18, alignItems: 'center'},
  sheetText: {fontSize: 16, color: t.t1},
}));
