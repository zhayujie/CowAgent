/** Copy without `keys`. Only pass optional fields: the result keeps the input's type. */
export function omit<T extends object>(obj: T, keys: readonly (keyof T)[]): T {
  const out = {...obj};
  for (const key of keys) {
    delete out[key];
  }
  return out;
}
