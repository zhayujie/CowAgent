import react from '@vitejs/plugin-react';
import path from 'node:path';
import {defineConfig} from 'vite';

// Browser preview for UI debugging only; native builds use Metro.
const BACKEND = process.env.COW_BACKEND ?? 'http://127.0.0.1:9899';
const API_PREFIXES = ['/auth', '/api', '/message', '/cancel', '/stream', '/ws', '/preview', '/upload', '/config', '/v1'];
const EXTENSIONS = ['.web.tsx', '.web.ts', '.web.js', '.tsx', '.ts', '.mjs', '.js', '.jsx', '.json'];
// Reanimated and worklets read process.env, which only Metro provides.
const DEFINE = {__DEV__: 'true', global: 'globalThis', 'process.env': '{"NODE_ENV":"development"}'};

export default defineConfig({
  root: __dirname,
  plugins: [react()],
  define: DEFINE,
  resolve: {
    alias: [
      {
        find: /^react-native$/,
        replacement: path.dirname(require.resolve('react-native-web/package.json')),
      },
    ],
    extensions: EXTENSIONS,
  },
  optimizeDeps: {
    rolldownOptions: {
      resolve: {extensions: EXTENSIONS},
      transform: {define: DEFINE},
      moduleTypes: {'.js': 'jsx'},
    },
  },
  server: {
    port: 8090,
    proxy: Object.fromEntries(
      API_PREFIXES.map(prefix => [
        prefix,
        {target: BACKEND, changeOrigin: true, ws: prefix === '/ws'},
      ]),
    ),
  },
});
