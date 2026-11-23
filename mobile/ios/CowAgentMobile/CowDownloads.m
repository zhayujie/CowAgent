#import <React/RCTBridgeModule.h>
#import <React/RCTUtils.h>
#import <UIKit/UIKit.h>

/*
 * Saving and sharing a file. iOS has no shared Downloads folder, so the file
 * is put in the app's temporary directory and handed to the share sheet, which
 * offers Save to Files, Save Image and sending it to other apps.
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

// Copies handed to other apps are only needed while those read them.
static const NSTimeInterval KeepCopies = 24 * 60 * 60;

static NSString *CopiesRoot(void)
{
  return [NSTemporaryDirectory() stringByAppendingPathComponent:@"shared"];
}

/** Removes what `root` holds from before the last day. */
static void Sweep(NSString *root)
{
  NSFileManager *files = NSFileManager.defaultManager;
  NSDate *cutoff = [NSDate dateWithTimeIntervalSinceNow:-KeepCopies];
  for (NSString *name in [files contentsOfDirectoryAtPath:root error:nil]) {
    NSString *path = [root stringByAppendingPathComponent:name];
    NSDate *modified = [files attributesOfItemAtPath:path error:nil].fileModificationDate;
    if (modified && [modified compare:cutoff] == NSOrderedAscending) {
      [files removeItemAtPath:path error:nil];
    }
  }
}

/** A fresh folder in the temporary directory, so the file keeps its own name without clashing. */
static NSURL *TempFile(NSString *name, NSError **error)
{
  Sweep(CopiesRoot());
  NSString *folder = [CopiesRoot() stringByAppendingPathComponent:NSUUID.UUID.UUIDString];
  if (![NSFileManager.defaultManager createDirectoryAtPath:folder withIntermediateDirectories:YES attributes:nil error:error]) {
    return nil;
  }
  return [[NSURL fileURLWithPath:folder isDirectory:YES] URLByAppendingPathComponent:name.length ? name : @"download"];
}

/** Fetches `url` into the temporary directory; `fileName` wins over the name the server suggests. */
static void Fetch(NSString *url, NSString *fileName, void (^done)(NSURL *file, NSError *error))
{
  NSURL *source = [NSURL URLWithString:url];
  if (!source) {
    done(nil, [NSError errorWithDomain:@"CowDownloads" code:0 userInfo:@{NSLocalizedDescriptionKey : @"Invalid URL"}]);
    return;
  }
  NSURLSessionDownloadTask *task = [NSURLSession.sharedSession
      downloadTaskWithURL:source
        completionHandler:^(NSURL *location, NSURLResponse *response, NSError *error) {
          NSInteger status =
              [response isKindOfClass:NSHTTPURLResponse.class] ? ((NSHTTPURLResponse *)response).statusCode : 0;
          if (error || !location || status >= 400) {
            NSString *message = error.localizedDescription ?: [NSString stringWithFormat:@"HTTP %ld", (long)status];
            done(nil, [NSError errorWithDomain:@"CowDownloads" code:status userInfo:@{NSLocalizedDescriptionKey : message}]);
            return;
          }
          NSString *name = SafeName(fileName);
          if (!name.length) {
            name = SafeName(response.suggestedFilename);
          }
          NSError *moveError = nil;
          NSURL *file = TempFile(name, &moveError);
          if (!file || ![NSFileManager.defaultManager moveItemAtURL:location toURL:file error:&moveError]) {
            done(nil, moveError);
            return;
          }
          done(file, nil);
        }];
  [task resume];
}

/**
 * The share sheet with `file`. Resolves when it closes: "photos" or "files" for those saves,
 * "other" for any other action, null when it was dismissed.
 */
static void Present(NSURL *file, RCTPromiseResolveBlock resolve, RCTPromiseRejectBlock reject)
{
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
}

@interface CowDownloads : NSObject <RCTBridgeModule>
@end

@implementation CowDownloads

RCT_EXPORT_MODULE()

+ (BOOL)requiresMainQueueSetup
{
  return NO;
}

- (instancetype)init
{
  if ((self = [super init])) {
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
      Sweep(CopiesRoot());
      // Files opened in the app from another one are copied here, which iOS keeps and backs up.
      NSString *documents = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES).firstObject;
      Sweep([documents stringByAppendingPathComponent:@"Inbox"]);
    });
  }
  return self;
}

/** Fetches the file, then offers the share sheet, which is where iOS saves files from. */
RCT_EXPORT_METHOD(save : (NSString *)url fileName : (NSString *)fileName resolve : (RCTPromiseResolveBlock)
                      resolve reject : (RCTPromiseRejectBlock)reject)
{
  Fetch(url, fileName, ^(NSURL *file, NSError *error) {
    if (!file) {
      reject(@"download_failed", error.localizedDescription, error);
      return;
    }
    Present(file, resolve, reject);
  });
}

/** The share sheet with the file itself, under its own name: a link is fetched first, a path on the phone copied. */
RCT_EXPORT_METHOD(share : (NSString *)source fileName : (NSString *)fileName mime : (NSString *)mime resolve : (RCTPromiseResolveBlock)
                      resolve reject : (RCTPromiseRejectBlock)reject)
{
  if ([source hasPrefix:@"http://"] || [source hasPrefix:@"https://"]) {
    Fetch(source, fileName, ^(NSURL *file, NSError *error) {
      if (!file) {
        reject(@"share_failed", error.localizedDescription, error);
        return;
      }
      Present(file, resolve, reject);
    });
    return;
  }
  NSURL *original = [source hasPrefix:@"file:"] ? [NSURL URLWithString:source] : [NSURL fileURLWithPath:source];
  // A file: link with spaces or other characters left unescaped parses to nothing.
  if (!original.isFileURL) {
    reject(@"share_failed", [NSString stringWithFormat:@"Not a file: %@", source], nil);
    return;
  }
  NSString *name = SafeName(fileName);
  NSError *error = nil;
  NSURL *file = TempFile(name.length ? name : original.lastPathComponent, &error);
  if (!file || ![NSFileManager.defaultManager copyItemAtURL:original toURL:file error:&error]) {
    reject(@"share_failed", error.localizedDescription, error);
    return;
  }
  Present(file, resolve, reject);
}

@end
