#import <Contacts/Contacts.h>
#import <CoreLocation/CoreLocation.h>
#import <EventKit/EventKit.h>
#import <Network/Network.h>
#import <React/RCTBridgeModule.h>
#import <UIKit/UIKit.h>
#import <UserNotifications/UserNotifications.h>
#import <sys/utsname.h>

/*
 * What the phone tools read from and add to the phone itself. The app has asked for the
 * permission before calling in; a missing one rejects with permission_denied.
 */

static const NSTimeInterval RecentFix = 120;
static const NSTimeInterval FixTimeout = 20;
static const NSUInteger MaxEvents = 200;
// iOS keeps at most 64 pending notifications per app.
static const NSUInteger MaxReminders = 50;
static NSString *const ReminderPrefix = @"cow-reminder-";
static NSString *const NoticePrefix = @"cow-notice-";
/** Shared with AppDelegate, which keeps the chat of a tapped notification under this default. */
static NSString *const TappedSessionKey = @"cow.notificationTap";

static dispatch_queue_t background(void)
{
  return dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0);
}

static NSString *text(id value)
{
  return [value isKindOfClass:NSString.class] ? value : @"";
}

static BOOL canReadEvents(EKAuthorizationStatus status)
{
  if (@available(iOS 17.0, *)) {
    return status == EKAuthorizationStatusFullAccess;
  }
  return status == EKAuthorizationStatusAuthorized;
}

static BOOL canAddEvents(EKAuthorizationStatus status)
{
  if (@available(iOS 17.0, *)) {
    return canReadEvents(status) || status == EKAuthorizationStatusWriteOnly;
  }
  return canReadEvents(status);
}

@interface CowDevice : NSObject <RCTBridgeModule, CLLocationManagerDelegate>
@end

@implementation CowDevice {
  CLLocationManager *_manager;
  NSMutableArray<NSArray *> *_waiting;
  UIBackgroundTaskIdentifier _hold;
}

RCT_EXPORT_MODULE()

+ (BOOL)requiresMainQueueSetup
{
  return NO;
}

/** What the update check compares against; a TestFlight build also moves to the same version on the App Store. */
- (NSDictionary *)constantsToExport
{
  NSBundle *bundle = NSBundle.mainBundle;
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
  // AppTransaction, its replacement, is Swift-only and asynchronous.
  BOOL testFlight = [bundle.appStoreReceiptURL.lastPathComponent isEqualToString:@"sandboxReceipt"];
#pragma clang diagnostic pop
  return @{
    @"appVersion" : text([bundle objectForInfoDictionaryKey:@"CFBundleShortVersionString"]),
    @"testFlight" : @(testFlight),
  };
}

- (dispatch_queue_t)methodQueue
{
  // CLLocationManager calls back on the thread it was made on, which needs a run loop.
  return dispatch_get_main_queue();
}

/** One location fix, with a street address when the phone can resolve one. */
RCT_EXPORT_METHOD(currentLocation : (RCTPromiseResolveBlock)resolve reject : (RCTPromiseRejectBlock)reject)
{
  if (!_manager) {
    _manager = [CLLocationManager new];
    _manager.delegate = self;
    _manager.desiredAccuracy = kCLLocationAccuracyHundredMeters;
    _waiting = [NSMutableArray new];
  }
  CLAuthorizationStatus status = _manager.authorizationStatus;
  if (status == kCLAuthorizationStatusDenied) {
    // Also what Location Services being off looks like. Asking which can stall the main thread.
    dispatch_async(background(), ^{
      if (CLLocationManager.locationServicesEnabled) {
        reject(@"permission_denied", @"Location permission not granted", nil);
      } else {
        reject(@"location_off", @"Location Services are off", nil);
      }
    });
    return;
  }
  if (status != kCLAuthorizationStatusAuthorizedWhenInUse && status != kCLAuthorizationStatusAuthorizedAlways) {
    reject(@"permission_denied", @"Location permission not granted", nil);
    return;
  }
  CLLocation *last = _manager.location;
  if (last && -last.timestamp.timeIntervalSinceNow < RecentFix) {
    [self describe:last resolve:resolve];
    return;
  }
  NSArray *callbacks = @[ resolve, reject ];
  [_waiting addObject:callbacks];
  if (_waiting.count == 1) {
    [_manager requestLocation];
  }
  dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(FixTimeout * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
    if ([self->_waiting containsObject:callbacks]) {
      [self->_waiting removeObject:callbacks];
      [self answer:@[ callbacks ] code:@"no_fix" message:@"No location fix" error:nil];
    }
  });
}

- (void)locationManager:(CLLocationManager *)manager didUpdateLocations:(NSArray<CLLocation *> *)locations
{
  CLLocation *location = locations.lastObject;
  NSArray *waiting = [_waiting copy];
  [_waiting removeAllObjects];
  for (NSArray *callbacks in waiting) {
    [self describe:location resolve:callbacks[0]];
  }
}

- (void)locationManager:(CLLocationManager *)manager didFailWithError:(NSError *)error
{
  NSArray *waiting = [_waiting copy];
  [_waiting removeAllObjects];
  if (error.code == kCLErrorDenied) {
    for (NSArray *callbacks in waiting) {
      ((RCTPromiseRejectBlock)callbacks[1])(@"permission_denied", error.localizedDescription, error);
    }
    return;
  }
  // requestLocation gives up for good on kCLErrorLocationUnknown too.
  [self answer:waiting code:@"no_fix" message:error.localizedDescription error:error];
}

/** Without a new fix, the phone's last one beats none; its time says how old it is. */
- (void)answer:(NSArray *)waiting code:(NSString *)code message:(NSString *)message error:(NSError *)error
{
  CLLocation *last = _manager.location;
  for (NSArray *callbacks in waiting) {
    if (last) {
      [self describe:last resolve:callbacks[0]];
    } else {
      ((RCTPromiseRejectBlock)callbacks[1])(code, message, error);
    }
  }
}

- (void)describe:(CLLocation *)location resolve:(RCTPromiseResolveBlock)resolve
{
  NSMutableDictionary *result = [@{
    @"latitude" : @(location.coordinate.latitude),
    @"longitude" : @(location.coordinate.longitude),
    @"time" : @(location.timestamp.timeIntervalSince1970 * 1000),
  } mutableCopy];
  if (location.horizontalAccuracy >= 0) {
    result[@"accuracy"] = @(location.horizontalAccuracy);
  }
  if (location.verticalAccuracy >= 0) {
    result[@"altitude"] = @(location.altitude);
  }
  [[CLGeocoder new] reverseGeocodeLocation:location
                         completionHandler:^(NSArray<CLPlacemark *> *placemarks, NSError *error) {
                           CLPlacemark *p = placemarks.firstObject;
                           if (p) {
                             NSMutableArray *parts = [NSMutableArray new];
                             for (NSString *part in @[
                                    p.country ?: @"", p.administrativeArea ?: @"", p.locality ?: @"",
                                    p.subLocality ?: @"", p.thoroughfare ?: @"", p.name ?: @""
                                  ]) {
                               if (part.length && ![parts containsObject:part]) {
                                 [parts addObject:part];
                               }
                             }
                             if (parts.count) {
                               result[@"address"] = [parts componentsJoinedByString:@" "];
                             }
                           }
                           resolve(result);
                         }];
}

/** Events in every calendar overlapping [start, end), recurring ones expanded. */
RCT_EXPORT_METHOD(calendarEvents : (double)start end : (double)end resolve : (RCTPromiseResolveBlock)resolve reject : (RCTPromiseRejectBlock)reject)
{
  dispatch_async(background(), ^{
    // Without access EventKit finds no events rather than failing.
    if (!canReadEvents([EKEventStore authorizationStatusForEntityType:EKEntityTypeEvent])) {
      reject(@"permission_denied", @"Calendar permission not granted", nil);
      return;
    }
    EKEventStore *store = [EKEventStore new];
    NSPredicate *predicate = [store predicateForEventsWithStartDate:[NSDate dateWithTimeIntervalSince1970:start / 1000]
                                                            endDate:[NSDate dateWithTimeIntervalSince1970:end / 1000]
                                                          calendars:nil];
    NSArray<EKEvent *> *events =
        [[store eventsMatchingPredicate:predicate] sortedArrayUsingSelector:@selector(compareStartDateWithEvent:)];
    NSMutableArray *list = [NSMutableArray new];
    for (EKEvent *event in events) {
      if (list.count >= MaxEvents) {
        break;
      }
      [list addObject:@{
        @"title" : text(event.title),
        @"start" : @(event.startDate.timeIntervalSince1970 * 1000),
        // Back to an exclusive end, as events are added and as Android gives them.
        @"end" : @((event.endDate.timeIntervalSince1970 + (event.allDay ? 1 : 0)) * 1000),
        @"allDay" : @(event.allDay),
        @"location" : text(event.location),
        @"notes" : text(event.notes),
        @"calendar" : text(event.calendar.title),
      }];
    }
    resolve(list);
  });
}

/** Adds an event to the default calendar. All-day events take local-midnight bounds, end exclusive. */
RCT_EXPORT_METHOD(createCalendarEvent : (NSDictionary *)input resolve : (RCTPromiseResolveBlock)resolve reject : (RCTPromiseRejectBlock)reject)
{
  dispatch_async(background(), ^{
    if (!canAddEvents([EKEventStore authorizationStatusForEntityType:EKEntityTypeEvent])) {
      reject(@"permission_denied", @"Calendar permission not granted", nil);
      return;
    }
    EKEventStore *store = [EKEventStore new];
    EKCalendar *calendar = store.defaultCalendarForNewEvents;
    if (!calendar) {
      reject(@"no_calendar", @"No calendar events can be added to", nil);
      return;
    }
    BOOL allDay = [input[@"allDay"] boolValue];
    EKEvent *event = [EKEvent eventWithEventStore:store];
    event.calendar = calendar;
    event.title = text(input[@"title"]);
    event.allDay = allDay;
    event.startDate = [NSDate dateWithTimeIntervalSince1970:[input[@"start"] doubleValue] / 1000];
    // EventKit ends an all-day event within its last day.
    event.endDate = [NSDate dateWithTimeIntervalSince1970:[input[@"end"] doubleValue] / 1000 - (allDay ? 1 : 0)];
    if (text(input[@"location"]).length) {
      event.location = input[@"location"];
    }
    if (text(input[@"notes"]).length) {
      event.notes = input[@"notes"];
    }
    if ([input[@"reminderMinutes"] isKindOfClass:NSNumber.class]) {
      [event addAlarm:[EKAlarm alarmWithRelativeOffset:-60 * [input[@"reminderMinutes"] doubleValue]]];
    }
    NSError *error;
    if (![store saveEvent:event span:EKSpanThisEvent commit:YES error:&error]) {
      reject(@"failed", error.localizedDescription, error);
      return;
    }
    resolve(@{@"id" : text(event.eventIdentifier), @"calendar" : text(calendar.title)});
  });
}

/** Contacts whose name matches, with their numbers, addresses and organization. */
RCT_EXPORT_METHOD(searchContacts : (NSString *)query limit : (double)limit resolve : (RCTPromiseResolveBlock)resolve reject : (RCTPromiseRejectBlock)reject)
{
  dispatch_async(background(), ^{
    NSArray<id<CNKeyDescriptor>> *keys = @[
      [CNContactFormatter descriptorForRequiredKeysForStyle:CNContactFormatterStyleFullName],
      CNContactPhoneNumbersKey, CNContactEmailAddressesKey, CNContactOrganizationNameKey,
    ];
    NSError *error;
    NSArray<CNContact *> *found = [[CNContactStore new] unifiedContactsMatchingPredicate:[CNContact predicateForContactsMatchingName:query]
                                                                            keysToFetch:keys
                                                                                  error:&error];
    if (!found) {
      reject(error.code == CNErrorCodeAuthorizationDenied ? @"permission_denied" : @"failed", error.localizedDescription, error);
      return;
    }
    NSMutableArray *list = [NSMutableArray new];
    for (CNContact *contact in found) {
      if (list.count >= limit) {
        break;
      }
      NSMutableArray *phones = [NSMutableArray new];
      for (CNLabeledValue<CNPhoneNumber *> *phone in contact.phoneNumbers) {
        [phones addObject:@{
          @"value" : text(phone.value.stringValue),
          @"label" : phone.label ? [CNLabeledValue localizedStringForLabel:phone.label] : @"",
        }];
      }
      NSMutableArray *emails = [NSMutableArray new];
      for (CNLabeledValue<NSString *> *email in contact.emailAddresses) {
        [emails addObject:@{
          @"value" : text(email.value),
          @"label" : email.label ? [CNLabeledValue localizedStringForLabel:email.label] : @"",
        }];
      }
      [list addObject:@{
        @"name" : text([CNContactFormatter stringFromContact:contact style:CNContactFormatterStyleFullName]),
        @"phones" : phones,
        @"emails" : emails,
        @"organization" : text(contact.organizationName),
      }];
    }
    resolve(list);
  });
}

/**
 * Battery, Low Power Mode, network and model; none of it needs a permission. Not disk space,
 * an API whose declared reasons all keep its answer on the device.
 */
RCT_EXPORT_METHOD(deviceStatus : (RCTPromiseResolveBlock)resolve reject : (RCTPromiseRejectBlock)reject)
{
  UIDevice *device = UIDevice.currentDevice;
  device.batteryMonitoringEnabled = YES;
  NSMutableDictionary *status = [NSMutableDictionary new];
  if (device.batteryLevel >= 0) {
    status[@"battery"] = @(lround(device.batteryLevel * 100));
  }
  status[@"charging"] = @(device.batteryState == UIDeviceBatteryStateCharging || device.batteryState == UIDeviceBatteryStateFull);
  status[@"powerSaving"] = @(NSProcessInfo.processInfo.lowPowerModeEnabled);
  struct utsname info;
  uname(&info);
  status[@"model"] = [NSString stringWithUTF8String:info.machine] ?: device.model;
  status[@"system"] = [NSString stringWithFormat:@"%@ %@", device.systemName, device.systemVersion];

  // The monitor answers once with the current path, then is let go.
  nw_path_monitor_t monitor = nw_path_monitor_create();
  dispatch_queue_t queue = dispatch_queue_create("ai.cowagent.network", DISPATCH_QUEUE_SERIAL);
  nw_path_monitor_set_queue(monitor, queue);
  __block BOOL answered = NO;
  nw_path_monitor_set_update_handler(monitor, ^(nw_path_t path) {
    if (answered) {
      return;
    }
    answered = YES;
    NSString *network = @"none";
    if (nw_path_get_status(path) == nw_path_status_satisfied) {
      network = nw_path_uses_interface_type(path, nw_interface_type_wifi)       ? @"wifi"
                : nw_path_uses_interface_type(path, nw_interface_type_cellular) ? @"cellular"
                : nw_path_uses_interface_type(path, nw_interface_type_wired)    ? @"ethernet"
                                                                                : @"other";
      status[@"metered"] = @(nw_path_is_expensive(path));
    }
    status[@"network"] = network;
    nw_path_monitor_cancel(monitor);
    resolve(status);
  });
  nw_path_monitor_start(monitor);
}

/** Replaces the reminders of scheduled tasks: `[{at (epoch ms), title, body, session}]`, soonest first. */
RCT_EXPORT_METHOD(scheduleReminders : (NSArray *)items resolve : (RCTPromiseResolveBlock)resolve reject : (RCTPromiseRejectBlock)reject)
{
  UNUserNotificationCenter *center = UNUserNotificationCenter.currentNotificationCenter;
  [center getPendingNotificationRequestsWithCompletionHandler:^(NSArray<UNNotificationRequest *> *pending) {
    NSMutableArray *ours = [NSMutableArray new];
    for (UNNotificationRequest *request in pending) {
      if ([request.identifier hasPrefix:ReminderPrefix]) {
        [ours addObject:request.identifier];
      }
    }
    [center removePendingNotificationRequestsWithIdentifiers:ours];
    NSTimeInterval now = NSDate.date.timeIntervalSince1970;
    NSUInteger added = 0;
    for (NSDictionary *item in items) {
      if (added >= MaxReminders) {
        break;
      }
      NSTimeInterval wait = [item[@"at"] doubleValue] / 1000 - now;
      if (wait < 1) {
        continue;
      }
      UNMutableNotificationContent *content = [UNMutableNotificationContent new];
      content.title = text(item[@"title"]);
      content.body = text(item[@"body"]);
      content.sound = UNNotificationSound.defaultSound;
      content.userInfo = @{@"session" : text(item[@"session"])};
      UNTimeIntervalNotificationTrigger *trigger = [UNTimeIntervalNotificationTrigger triggerWithTimeInterval:wait repeats:NO];
      NSString *identifier = [NSString stringWithFormat:@"%@%lu", ReminderPrefix, (unsigned long)added++];
      [center addNotificationRequest:[UNNotificationRequest requestWithIdentifier:identifier content:content trigger:trigger]
               withCompletionHandler:nil];
    }
    resolve(@(added));
  }];
}

/**
 * A reply or a scheduled task's result that came while the app was away; a newer one for the
 * same key takes its place. On screen AppDelegate shows none. Tapping it opens `session`.
 */
RCT_EXPORT_METHOD(notice : (NSString *)kind key : (NSString *)key title : (NSString *)title body : (NSString *)body session : (NSString *)session resolve : (RCTPromiseResolveBlock)resolve reject : (RCTPromiseRejectBlock)reject)
{
  UNMutableNotificationContent *content = [UNMutableNotificationContent new];
  content.title = text(title);
  content.body = text(body);
  content.sound = UNNotificationSound.defaultSound;
  content.userInfo = @{@"session" : text(session)};
  NSString *identifier = [NSString stringWithFormat:@"%@%@-%@", NoticePrefix, text(kind), text(key)];
  [UNUserNotificationCenter.currentNotificationCenter
      addNotificationRequest:[UNNotificationRequest requestWithIdentifier:identifier content:content trigger:nil]
       withCompletionHandler:^(NSError *error) {
         if (error) {
           reject(@"notice_failed", error.localizedDescription, error);
         } else {
           resolve(nil);
         }
       }];
}

/** The chat of the notification the app was last opened from, once. */
RCT_EXPORT_METHOD(takeNotificationTap : (RCTPromiseResolveBlock)resolve reject : (RCTPromiseRejectBlock)reject)
{
  NSUserDefaults *defaults = NSUserDefaults.standardUserDefaults;
  NSString *session = [defaults stringForKey:TappedSessionKey];
  [defaults removeObjectForKey:TappedSessionKey];
  resolve(session.length ? session : nil);
}

/** Held while a reply is under way, so leaving the app buys it the half minute or so iOS grants. */
RCT_EXPORT_METHOD(holdBackground)
{
  if (_hold != UIBackgroundTaskInvalid) {
    return;
  }
  // Ends the task it was given for, even with the module gone, or iOS ends the app instead.
  __block UIBackgroundTaskIdentifier task = UIBackgroundTaskInvalid;
  __weak CowDevice *weakSelf = self;
  task = [UIApplication.sharedApplication beginBackgroundTaskWithName:@"reply"
                                                    expirationHandler:^{
                                                      [UIApplication.sharedApplication endBackgroundTask:task];
                                                      CowDevice *strongSelf = weakSelf;
                                                      if (strongSelf && strongSelf->_hold == task) {
                                                        strongSelf->_hold = UIBackgroundTaskInvalid;
                                                      }
                                                    }];
  _hold = task;
}

RCT_EXPORT_METHOD(releaseBackground)
{
  if (_hold == UIBackgroundTaskInvalid) {
    return;
  }
  [UIApplication.sharedApplication endBackgroundTask:_hold];
  _hold = UIBackgroundTaskInvalid;
}

@end
