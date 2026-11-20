import {Platform} from 'react-native';

/** A file the user picked or recorded, ready to be uploaded. */
export interface PickedFile {
  uri: string;
  name: string;
  type: string;
  size?: number;
  /** Browser builds hold the bytes directly instead of a file URI. */
  blob?: Blob;
}

export type Recording = PickedFile & {durationMs: number};

export function appendFile(form: FormData, field: string, file: PickedFile) {
  if (file.blob) {
    // React Native's FormData typing lacks the browser's filename argument.
    (form as unknown as {append(n: string, v: Blob, f: string): void}).append(field, file.blob, file.name);
  } else {
    // React Native's FormData streams the file from its URI. HarmonyOS hands the URI to
    // the system HTTP client as a sandbox path, which fails with a file:// scheme.
    const uri = (Platform.OS as string) === 'harmony' ? file.uri.replace(/^file:\/\//, '') : file.uri;
    form.append(field, {uri, name: file.name, type: file.type} as unknown as Blob);
  }
}

export const isImageType = (type?: string) => !!type && type.startsWith('image/');
