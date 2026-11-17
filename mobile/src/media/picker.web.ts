/// <reference lib="dom" />
import type {PickedFile} from './types';

export const canTakePhoto = true;

const MAX_PICK = 9;

/** Browsers only expose files through an <input>; resolve once the user picks or backs out. */
function chooseFiles(accept: string, capture?: string): Promise<PickedFile[]> {
  return new Promise(resolve => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = accept;
    input.multiple = !capture;
    if (capture) {
      input.setAttribute('capture', capture);
    }
    input.style.display = 'none';
    let settled = false;
    const done = (files: PickedFile[]) => {
      if (!settled) {
        settled = true;
        input.remove();
        resolve(files);
      }
    };
    input.addEventListener('change', () => {
      const files = Array.from(input.files ?? []).slice(0, MAX_PICK);
      done(
        files.map(f => ({
          uri: URL.createObjectURL(f),
          name: f.name,
          type: f.type || 'application/octet-stream',
          size: f.size,
          blob: f,
        })),
      );
    });
    input.addEventListener('cancel', () => done([]));
    document.body.appendChild(input);
    input.click();
  });
}

export const pickPhotos = () => chooseFiles('image/*');
export const pickAvatar = async (): Promise<PickedFile | null> =>
  (await chooseFiles('image/png,image/jpeg,image/webp,image/gif'))[0] ?? null;
export const takePhoto = () => chooseFiles('image/*', 'environment');
export const pickDocuments = (imagesOnly = false) => chooseFiles(imagesOnly ? 'image/*' : '*/*');
