import { execFileSync } from 'child_process';
import * as path from 'path';
import { hapTasks } from '@ohos/hvigor-ohos-plugin';
import { HvigorNode, HvigorPlugin } from '@ohos/hvigor';
import { createRNOHModulePlugin } from '@rnoh/hvigor-plugin';

/**
 * Stages the embedded agent kernel (mobile/kernel/harmony_assets.py) into
 * rawfile/cow-kernel before every build. Needs Python 3 on the build machine;
 * set COW_PYTHON if it is not `python` (Windows) or `python3` on PATH. Without
 * Python the build goes on with whatever was staged last.
 */
function cowKernelPlugin(): HvigorPlugin {
  return {
    pluginId: 'cowKernelPlugin',
    apply(node: HvigorNode) {
      node.registerTask({
        name: 'bundleCowKernel',
        run: () => {
          const python = process.env.COW_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
          const script = path.resolve(__dirname, '../../kernel/harmony_assets.py');
          const rawfile = path.resolve(__dirname, 'src/main/resources/rawfile');
          try {
            execFileSync(python, [script, rawfile], { stdio: 'inherit' });
          } catch (e) {
            if ((e as NodeJS.ErrnoException).code !== 'ENOENT') {
              throw e;
            }
            console.warn(`cow-kernel: ${python} not found, set COW_PYTHON; the kernel sources were not updated`);
          }
        },
        postDependencies: ['default@PreBuild'],
      });
    },
  };
}

export default {
  system: hapTasks,
  plugins: [
    createRNOHModulePlugin({
      codegen: {
        rnohModulePath: './oh_modules/@rnoh/react-native-openharmony',
      },
    }),
    cowKernelPlugin(),
  ],
};
