import { TurboModule } from '@rnoh/react-native-openharmony/ts';
import { scanBarcode, scanCore } from '@kit.ScanKit';
import { camera, cameraPicker } from '@kit.CameraKit';
import { photoAccessHelper } from '@kit.MediaLibraryKit';
import { fileIo, fileUri, picker } from '@kit.CoreFileKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { http } from '@kit.NetworkKit';

const DOWNLOAD_TIMEOUT_MS = 10 * 60 * 1000;

function safeName(name: string): string {
  return name.replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_').trim().replace(/^\.+/, '');
}

export const COW_NATIVE_MODULE = 'CowNative';

/** A file copied into the app sandbox, so the networking module can upload it by path. */
export interface NativeFile {
  path: string;
  name: string;
  size: number;
}

/**
 * System pickers (Scan Kit, camera picker, photo picker) and saving to Downloads. The
 * pickers run in a system process and hand back only what the user chose, and the
 * Downloads folder comes from the document picker, so none of it needs a permission.
 */
export class CowNativeModule extends TurboModule {
  private downloadDir: string | null = null;
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
      throw err;
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

  /** Streams the file into Downloads/<app name>; resolves with the name it was saved under. */
  async saveDownload(url: string, fileName: string): Promise<string> {
    const dir = await this.getDownloadDir();
    const name = this.freeName(dir, safeName(fileName) || 'download');
    const path = `${dir}/${name}`;
    const file = fileIo.openSync(path, fileIo.OpenMode.CREATE | fileIo.OpenMode.WRITE_ONLY | fileIo.OpenMode.TRUNC);
    const req = http.createHttp();
    req.on('dataReceive', (data: ArrayBuffer) => {
      fileIo.writeSync(file.fd, data);
    });
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
      req.destroy();
      fileIo.closeSync(file);
      if (!saved) {
        fileIo.unlinkSync(path);
      }
    }
    return name;
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
