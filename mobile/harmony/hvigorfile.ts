import * as path from 'path';
import { appTasks } from '@ohos/hvigor-ohos-plugin';
import { createRNOHProjectPlugin } from '@rnoh/hvigor-plugin';

export default {
  system: appTasks,
  plugins: [
    // Release builds rebundle the JS into the file Index.ets loads; the plugin's default
    // output, bundle.harmony.js, is never read, so the app kept an old bundle.
    createRNOHProjectPlugin({
      nodeModulesPath: path.resolve(__dirname, '../node_modules'),
      bundler: {
        jsEngine: 'hermes',
        bundleOutput: path.resolve(__dirname, 'entry/src/main/resources/rawfile/hermes_bundle.hbc'),
      },
    }),
  ],
};
