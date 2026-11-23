import { TurboModule, TurboModuleContext } from '@rnoh/react-native-openharmony/ts';
import { scanBarcode, scanCore } from '@kit.ScanKit';
import { camera, cameraPicker } from '@kit.CameraKit';
import { photoAccessHelper } from '@kit.MediaLibraryKit';
import { fileIo, fileUri, picker } from '@kit.CoreFileKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { http } from '@kit.NetworkKit';
import { systemShare } from '@kit.ShareKit';
import { uniformTypeDescriptor } from '@kit.ArkData';
import { util } from '@kit.ArkTS';
import { SharedIntake } from './SharedIntake';

const DOWNLOAD_TIMEOUT_MS = 10 * 60 * 1000;
const PROGRESS_INTERVAL_MS = 100;
const MAX_SHARED = 9;
const KEEP_MS = 24 * 60 * 60 * 1000;

function safeName(name: string): string {
  return name.replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_').trim().replace(/^\.+/, '');
}

function lastSegment(url: string): string {
  const last = url.split(/[?#]/)[0].split('/').pop() ?? '';
  try {
    return decodeURIComponent(last);
  } catch (e) {
    return last;
  }
}

function utdOf(name: string): string {
  const dot = name.lastIndexOf('.');
  try {
    return dot > 0 ? uniformTypeDescriptor.getUniformDataTypeByFilenameExtension(name.substring(dot)) : 'general.file';
  } catch (e) {
    return 'general.file';
  }
}

function mimeOf(utd: string): string {
  try {
    return uniformTypeDescriptor.getTypeDescriptor(utd).mimeTypes[0] ?? 'application/octet-stream';
  } catch (e) {
    return 'application/octet-stream';
  }
}

/** Only a file another app hands over; one naming this app, or no app, could reach into its own sandbox. */
function fromOtherApp(uri: string, bundleName: string): boolean {
  let decoded: string;
  try {
    decoded = decodeURIComponent(uri);
  } catch (e) {
    return false;
  }
  const match = /^file:\/\/([^/?#]*)/i.exec(decoded);
  const authority = match === null ? '' : match[1].substring(match[1].lastIndexOf('@') + 1);
  return authority !== '' && authority.toLowerCase() !== bundleName.toLowerCase() &&
    !/(^|\/)\.\.(\/|$)/.test(decoded);
}

function removeTree(path: string): void {
  if (fileIo.statSync(path).isDirectory()) {
    fileIo.rmdirSync(path);
  } else {
    fileIo.unlinkSync(path);
  }
}

/** A new folder under `root`, after clearing out what earlier calls left there a day ago. */
function freshFolder(root: string): string {
  if (fileIo.accessSync(root)) {
    const cutoff = (Date.now() - KEEP_MS) / 1000;
    for (const name of fileIo.listFileSync(root)) {
      try {
        if (fileIo.statSync(`${root}/${name}`).mtime < cutoff) {
          removeTree(`${root}/${name}`);
        }
      } catch (e) {
        // Gone already.
      }
    }
  }
  const folder = `${root}/${util.generateRandomUUID()}`;
  fileIo.mkdirSync(folder, true);
  return folder;
}

export const COW_NATIVE_MODULE = 'CowNative';

/** A file copied into the app sandbox, so the networking module can upload it by path. */
export interface NativeFile {
  path: string;
  name: string;
  size: number;
}

/** A file another app shared, as the chat composer takes picked files. */
export interface SharedFile {
  uri: string;
  name: string;
  type: string;
  size: number;
}

export interface SharedIn {
  files: SharedFile[];
  text: string;
}

interface Progress {
  id: string;
  loaded: number;
  total: number;
}

/**
 * System pickers (Scan Kit, camera picker, photo picker), saving to Downloads and the
 * share panel. The pickers run in a system process and hand back only what the user
 * chose, and the Downloads folder comes from the document picker, so none of it needs
 * a permission.
 */
export class CowNativeModule extends TurboModule {
  private downloadDir: string | null = null;
  private readonly sharedArrived = () => this.ctx.rnInstance.emitDeviceEvent('cowShared', null);

  constructor(ctx: TurboModuleContext) {
    super(ctx);
    SharedIntake.onArrive = this.sharedArrived;
  }

  __onDestroy__(): void {
    if (SharedIntake.onArrive === this.sharedArrived) {
      SharedIntake.onArrive = null;
    }
  }
  /** Resolves with the QR code text, or null when the user backs out. */
  async scan(): Promise<string | null> {
    const options: scanBarcode.ScanOptions = {
      scanTypes: [scanCore.ScanType.QR_CODE],
      enableMultiMode: false,
      enableAlbum: true,
    };
    try {
      const result = await scanBarcode.startScanForResult(this.ctx.uiAbilityContext, options);
      return result.originalValue;
    } catch (e) {
      const err = e as BusinessError;
      if (err.code === scanCore.ScanErrorCode.SCAN_SERVICE_CANCELED) {
        return null;
      }
      throw err as Error;
    }
  }

  /** Resolves with the photo, or null when the user backs out. */
  async takePhoto(): Promise<NativeFile | null> {
    const name = `photo_${Date.now()}.jpg`;
    const path = `${this.ctx.uiAbilityContext.cacheDir}/${name}`;
    // The camera writes into saveUri, which has to exist beforehand.
    fileIo.closeSync(fileIo.openSync(path, fileIo.OpenMode.CREATE | fileIo.OpenMode.READ_WRITE));
    const profile: cameraPicker.PickerProfile = {
      cameraPosition: camera.CameraPosition.CAMERA_POSITION_BACK,
      saveUri: fileUri.getUriFromPath(path),
    };
    let size = 0;
    try {
      const result = await cameraPicker.pick(this.ctx.uiAbilityContext, [cameraPicker.PickerMediaType.PHOTO], profile);
      size = result.resultCode === 0 ? fileIo.statSync(path).size : 0;
    } finally {
      if (size === 0) {
        fileIo.unlinkSync(path);
      }
    }
    return size > 0 ? { path, name, size } : null;
  }

  /** Empty when the user backs out. */
  async pickPhotos(max: number): Promise<NativeFile[]> {
    const options = new photoAccessHelper.PhotoSelectOptions();
    options.MIMEType = photoAccessHelper.PhotoViewMIMETypes.IMAGE_TYPE;
    options.maxSelectNumber = max;
    const result = await new photoAccessHelper.PhotoViewPicker().select(options);
    const cacheDir = this.ctx.uiAbilityContext.cacheDir;
    const stamp = Date.now();
    const files: NativeFile[] = [];
    for (let i = 0; i < result.photoUris.length; i++) {
      const uri = result.photoUris[i];
      const name = new fileUri.FileUri(uri).name || `photo_${stamp}_${i}.jpg`;
      const path = `${cacheDir}/pick_${stamp}_${i}_${name}`;
      // The picker's grant on gallery URIs is temporary, so uploads read a sandbox copy.
      const src = fileIo.openSync(uri, fileIo.OpenMode.READ_ONLY);
      try {
        fileIo.copyFileSync(src.fd, path);
      } finally {
        fileIo.closeSync(src);
      }
      files.push({ path, name, size: fileIo.statSync(path).size });
    }
    return files;
  }

  /**
   * Streams the file into Downloads/<app name>; resolves with the name it was saved under.
   * With an `id`, `cowDownloadProgress` events tell how far it got.
   */
  async saveDownload(url: string, fileName: string, id?: string): Promise<string> {
    const dir = await this.getDownloadDir();
    const name = this.freeName(dir, safeName(fileName) || safeName(lastSegment(url)) || 'download');
    await this.fetchInto(url, `${dir}/${name}`, id);
    return name;
  }

  /** The system share panel with the file itself: a link is fetched first, a path on the phone copied. */
  async share(source: string, fileName: string, _mime: string): Promise<boolean> {
    const name = safeName(fileName) || safeName(lastSegment(source)) || 'file';
    const path = `${freshFolder(`${this.ctx.uiAbilityContext.cacheDir}/share`)}/${name}`;
    if (/^https?:\/\//i.test(source)) {
      await this.fetchInto(source, path);
    } else {
      fileIo.copyFileSync(source.startsWith('file://') ? new fileUri.FileUri(source).path : source, path);
    }
    const data = new systemShare.SharedData({ utd: utdOf(name), uri: fileUri.getUriFromPath(path), title: name });
    await new systemShare.ShareController(data).show(this.ctx.uiAbilityContext, {
      previewMode: systemShare.SharePreviewMode.DETAIL,
      selectionMode: systemShare.SelectionMode.SINGLE,
    });
    return true;
  }

  /** What another app last shared here, copied into the cache; null when nothing is waiting. */
  async takeShared(): Promise<SharedIn | null> {
    const want = SharedIntake.take();
    if (want === null) {
      return null;
    }
    const records = (await systemShare.getSharedData(want)).getRecords();
    const bundleName = this.ctx.uiAbilityContext.abilityInfo.bundleName;
    const folder = freshFolder(`${this.ctx.uiAbilityContext.cacheDir}/shared-in`);
    const files: SharedFile[] = [];
    const texts: string[] = [];
    for (let i = 0; i < records.length && files.length < MAX_SHARED; i++) {
      const record = records[i];
      if (!record.uri) {
        if (record.content) {
          texts.push(record.content);
        }
        continue;
      }
      if (!fromOtherApp(record.uri, bundleName)) {
        continue;
      }
      // One the sender no longer lets this app read is left out, not the whole share.
      try {
        // A title may be a caption without the extension the file name has.
        const title = safeName(record.title ?? '');
        const name = (title.includes('.') ? title : safeName(new fileUri.FileUri(record.uri).name)) || title || 'file';
        const dir = `${folder}/${i}`;
        fileIo.mkdirSync(dir);
        const path = `${dir}/${name}`;
        const src = fileIo.openSync(record.uri, fileIo.OpenMode.READ_ONLY);
        try {
          fileIo.copyFileSync(src.fd, path);
        } finally {
          fileIo.closeSync(src);
        }
        files.push({ uri: `file://${path}`, name, type: mimeOf(record.utd), size: fileIo.statSync(path).size });
      } catch (e) {
        continue;
      }
    }
    return { files, text: texts.join('\n') };
  }

  private async fetchInto(url: string, path: string, id?: string): Promise<void> {
    const file = fileIo.openSync(path, fileIo.OpenMode.CREATE | fileIo.OpenMode.WRITE_ONLY | fileIo.OpenMode.TRUNC);
    const req = http.createHttp();
    req.on('dataReceive', (data: ArrayBuffer) => {
      fileIo.writeSync(file.fd, data);
    });
    if (id) {
      let last = 0;
      req.on('dataReceiveProgress', (info: http.DataReceiveProgressInfo) => {
        const now = Date.now();
        if (now - last >= PROGRESS_INTERVAL_MS || info.receiveSize === info.totalSize) {
          last = now;
          const progress: Progress = { id, loaded: info.receiveSize, total: info.totalSize };
          this.ctx.rnInstance.emitDeviceEvent('cowDownloadProgress', progress);
        }
      });
    }
    let saved = false;
    try {
      const code = await req.requestInStream(url, {
        method: http.RequestMethod.GET,
        connectTimeout: 30000,
        readTimeout: DOWNLOAD_TIMEOUT_MS,
      });
      if (code < 200 || code >= 300) {
        throw new Error(`HTTP ${code}`);
      }
      saved = true;
    } finally {
      req.off('dataReceive');
      if (id) {
        req.off('dataReceiveProgress');
      }
      req.destroy();
      fileIo.closeSync(file);
      if (!saved) {
        fileIo.unlinkSync(path);
      }
    }
  }

  /** DOWNLOAD mode shows no UI: it hands back the app's own folder under Downloads. */
  private async getDownloadDir(): Promise<string> {
    if (this.downloadDir === null) {
      const options = new picker.DocumentSaveOptions();
      options.pickerMode = picker.DocumentPickerMode.DOWNLOAD;
      const uris = await new picker.DocumentViewPicker(this.ctx.uiAbilityContext).save(options);
      this.downloadDir = new fileUri.FileUri(uris[0]).path;
    }
    return this.downloadDir;
  }

  /** `report.pdf`, then `report (1).pdf`, ... so an earlier download is never overwritten. */
  private freeName(dir: string, name: string): string {
    const dot = name.lastIndexOf('.');
    const stem = dot > 0 ? name.substring(0, dot) : name;
    const ext = dot > 0 ? name.substring(dot) : '';
    let candidate = name;
    for (let i = 1; fileIo.accessSync(`${dir}/${candidate}`); i++) {
      candidate = `${stem} (${i})${ext}`;
    }
    return candidate;
  }
}
