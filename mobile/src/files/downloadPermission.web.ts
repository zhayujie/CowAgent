/** The browser saves through an anchor, which asks for nothing. */
export async function canWriteDownloads(): Promise<boolean> {
  return true;
}
