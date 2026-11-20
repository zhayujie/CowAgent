/**
 * Importing some ets files in the following way results in runtime errors e.g.
 * import { setupRNOHWorker } from "@rnoh/react-native-openharmony"
 *
 * It looks like this is ArkTS problem and it may be fixed in the future.
 * For the time being, use direct imports.
 */
import { setupRNOHWorker } from "@rnoh/react-native-openharmony/src/main/ets/setupRNOHWorker"
import { getRNOHPackages } from "../PackageProvider"

setupRNOHWorker({
  createWorkerRNInstanceConfig: (_rnInstanceName) => {
    return { thirdPartyPackagesFactory: getRNOHPackages }
  }
})

