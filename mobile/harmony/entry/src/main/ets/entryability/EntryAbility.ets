import {RNAbility} from '@rnoh/react-native-openharmony';
import type {AbilityConstant, Want} from '@kit.AbilityKit';
import {NotificationTap, SharedIntake} from '../native/SharedIntake';

export default class EntryAbility extends RNAbility {
  override onCreate(want: Want, launchParam?: AbilityConstant.LaunchParam) {
    SharedIntake.offer(want);
    NotificationTap.offer(want);
    super.onCreate(want, launchParam);
  }

  override onNewWant(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    SharedIntake.offer(want);
    NotificationTap.offer(want);
    super.onNewWant(want, launchParam);
  }

  override getPagePath() {
    return 'pages/Index';
  }

  override getRNOHWorkerScriptUrl() {
    return "entry/ets/workers/RNOHWorker.ets"
  }
}
