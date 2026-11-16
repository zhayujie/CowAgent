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
    // React Native's FormData streams the file from its URI.
    form.append(field, {uri: file.uri, name: file.name, type: file.type} as unknown as Blob);
  }
}

export const isImageType = (type?: string) => !!type && type.startsWith('image/');
