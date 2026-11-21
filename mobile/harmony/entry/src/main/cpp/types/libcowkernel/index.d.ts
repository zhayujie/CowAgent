export interface KernelConfig {
  /** sys.prefix; nothing is read from it since pythonPath is explicit. */
  pythonHome: string;
  /** The complete sys.path before the sources: stdlib.zip and site-packages.zip. */
  pythonPath: string[];
  /** Where the bytecode of the kernel sources is cached. */
  pycache: string;
  /** The unpacked kernel sources, holding app.py. */
  sources: string;
  /** The kernel's working directory. */
  home: string;
  /** Set in os.environ before app.py is imported. */
  env: Record<string, string>;
}

/** False in builds made without the Python runtime. */
export const available: () => boolean;
export const isRunning: () => boolean;
/** The preferred port if it is free on loopback, else any free one; 0 when none is. */
export const pickPort: (preferred: number) => number;
/** Starts the kernel on its own thread; false when it is already running. */
export const start: (config: KernelConfig) => boolean;
