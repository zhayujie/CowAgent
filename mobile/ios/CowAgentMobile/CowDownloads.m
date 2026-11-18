#import <React/RCTBridgeModule.h>
#import <React/RCTUtils.h>
#import <UIKit/UIKit.h>

/*
 * Saving a file from the server. iOS has no shared Downloads folder, so the
 * file is fetched into the app's temporary directory and handed to the share
 * sheet, which offers Save to Files, Save Image and sending it to other apps.
 */

static NSString *SafeName(NSString *name)
{
  NSCharacterSet *invalid = [NSCharacterSet characterSetWithCharactersInString:@"/\\:*?\"<>|"];
  NSString *clean = [[[name ?: @"" componentsSeparatedByCharactersInSet:invalid] componentsJoinedByString:@"_"]
      stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
  while ([clean hasPrefix:@"."]) {
    clean = [clean substringFromIndex:1];
  }
  return clean;
}

@interface CowDownloads : NSObject <RCTBridgeModule>
@end

@implementation CowDownloads

RCT_EXPORT_MODULE()

+ (BOOL)requiresMainQueueSetup
{
  return NO;
}

/**
 * Resolves when the share sheet closes: "photos" or "files" for those saves,
 * "other" for any other action, null when it was dismissed.
 */
RCT_EXPORT_METHOD(save : (NSString *)url fileName : (NSString *)fileName resolve : (RCTPromiseResolveBlock)
                      resolve reject : (RCTPromiseRejectBlock)reject)
{
  NSURL *source = [NSURL URLWithString:url];
  if (!source) {
    reject(@"download_failed", @"Invalid URL", nil);
    return;
  }
  NSURLSessionDownloadTask *task = [NSURLSession.sharedSession
      downloadTaskWithURL:source
        completionHandler:^(NSURL *location, NSURLResponse *response, NSError *error) {
          NSInteger status =
              [response isKindOfClass:NSHTTPURLResponse.class] ? ((NSHTTPURLResponse *)response).statusCode : 0;
          if (error || !location || status >= 400) {
            NSString *message = error.localizedDescription ?: [NSString stringWithFormat:@"HTTP %ld", (long)status];
            reject(@"download_failed", message, error);
            return;
          }
          NSString *name = SafeName(fileName);
          if (!name.length) {
            name = SafeName(response.suggestedFilename);
          }
          if (!name.length) {
            name = @"download";
          }
          // A folder per download keeps the original name without clashing with earlier ones.
          NSString *folder = [NSTemporaryDirectory() stringByAppendingPathComponent:NSUUID.UUID.UUIDString];
          NSURL *file = [[NSURL fileURLWithPath:folder isDirectory:YES] URLByAppendingPathComponent:name];
          NSFileManager *fm = NSFileManager.defaultManager;
          NSError *moveError = nil;
          if (![fm createDirectoryAtPath:folder withIntermediateDirectories:YES attributes:nil error:&moveError] ||
              ![fm moveItemAtURL:location toURL:file error:&moveError]) {
            reject(@"download_failed", moveError.localizedDescription, moveError);
            return;
          }
          dispatch_async(dispatch_get_main_queue(), ^{
            UIViewController *top = RCTPresentedViewController();
            if (!top) {
              reject(@"download_failed", @"Nothing to present the share sheet from", nil);
              return;
            }
            UIActivityViewController *sheet = [[UIActivityViewController alloc] initWithActivityItems:@[ file ]
                                                                                applicationActivities:nil];
            // iPad shows the sheet as a popover, which needs an anchor.
            UIPopoverPresentationController *popover = sheet.popoverPresentationController;
            popover.sourceView = top.view;
            popover.sourceRect = CGRectMake(CGRectGetMidX(top.view.bounds), CGRectGetMidY(top.view.bounds), 0, 0);
            popover.permittedArrowDirections = 0;
            __block BOOL settled = NO;
            sheet.completionWithItemsHandler = ^(UIActivityType activityType, BOOL completed, NSArray *items,
                                                 NSError *activityError) {
              if (settled) {
                return;
              }
              settled = YES;
              if (!completed) {
                resolve([NSNull null]);
              } else if ([activityType isEqualToString:UIActivityTypeSaveToCameraRoll]) {
                resolve(@"photos");
              } else if ([activityType containsString:@"SaveToFiles"]) {
                resolve(@"files");
              } else {
                resolve(@"other");
              }
            };
            [top presentViewController:sheet animated:YES completion:nil];
          });
        }];
  [task resume];
}

@end
