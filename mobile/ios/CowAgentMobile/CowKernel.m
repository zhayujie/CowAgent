#import <React/RCTBridgeModule.h>

#import <Python/Python.h>
#import <Security/SecRandom.h>
#include <arpa/inet.h>
#include <os/log.h>
#include <sys/socket.h>
#include <unistd.h>

/*
 * The agent kernel running inside this app: the CowAgent Python backend in
 * its `mobile` deployment, serving the usual web console API on loopback.
 *
 * Process-wide rather than per React instance, so a JS reload finds the kernel
 * that is already running instead of starting a second one on the same data.
 */

static NSString *const kPasswordKey = @"cow_kernel.password";
static NSString *const kPortKey = @"cow_kernel.port";
static NSString *const kSourcesStampKey = @"cow_kernel.sources_stamp";
static NSString *const kSourcesDir = @"cow-kernel";

static os_log_t kernelLog;
static NSDictionary *endpoint;
static BOOL pythonReady;
static BOOL running;

static NSError *KernelError(NSString *message)
{
  return [NSError errorWithDomain:@"CowKernel" code:1 userInfo:@{NSLocalizedDescriptionKey : message}];
}

static NSString *NewSecret(void)
{
  uint8_t bytes[24];
  if (SecRandomCopyBytes(kSecRandomDefault, sizeof(bytes), bytes) != errSecSuccess) {
    return nil;
  }
  NSMutableString *hex = [NSMutableString stringWithCapacity:sizeof(bytes) * 2];
  for (size_t i = 0; i < sizeof(bytes); i++) {
    [hex appendFormat:@"%02x", bytes[i]];
  }
  return hex;
}

/** Bind 127.0.0.1:port (0 = any free port) and return the bound port, or 0 on failure. */
static int TryBind(int port)
{
  int fd = socket(AF_INET, SOCK_STREAM, 0);
  if (fd < 0) {
    return 0;
  }
  struct sockaddr_in addr = {0};
  addr.sin_len = sizeof(addr);
  addr.sin_family = AF_INET;
  addr.sin_port = htons((uint16_t)port);
  addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  socklen_t len = sizeof(addr);
  int bound = 0;
  if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) == 0 &&
      getsockname(fd, (struct sockaddr *)&addr, &len) == 0) {
    bound = ntohs(addr.sin_port);
  }
  close(fd);
  return bound;
}

/** The last port if it is still free, so the saved server address keeps working. */
static int PickPort(int preferred)
{
  int port = preferred > 0 ? TryBind(preferred) : 0;
  return port > 0 ? port : TryBind(0);
}

/**
 * Copy the kernel sources out of the read-only app bundle once per install or
 * update, so the kernel runs from a writable tree as it does everywhere else.
 */
static NSString *InstallSources(NSString *home, NSUserDefaults *prefs, NSError **error)
{
  NSFileManager *fm = NSFileManager.defaultManager;
  NSBundle *bundle = NSBundle.mainBundle;
  NSString *dest = [home stringByAppendingPathComponent:kSourcesDir];
  NSDate *built = [fm attributesOfItemAtPath:bundle.executablePath error:nil].fileModificationDate;
  NSString *stamp = [NSString stringWithFormat:@"%@-%.0f",
                                               [bundle objectForInfoDictionaryKey:@"CFBundleVersion"],
                                               built.timeIntervalSince1970];
  BOOL isDir = NO;
  if ([fm fileExistsAtPath:dest isDirectory:&isDir] && isDir &&
      [[prefs stringForKey:kSourcesStampKey] isEqualToString:stamp]) {
    return dest;
  }
  NSString *bundled = [bundle.resourcePath stringByAppendingPathComponent:kSourcesDir];
  NSString *staging = [dest stringByAppendingString:@".tmp"];
  [fm removeItemAtPath:staging error:nil];
  if (![fm copyItemAtPath:bundled toPath:staging error:error]) {
    return nil;
  }
  [fm removeItemAtPath:dest error:nil];
  if (![fm moveItemAtPath:staging toPath:dest error:error]) {
    return nil;
  }
  [prefs setObject:stamp forKey:kSourcesStampKey];
  return dest;
}

/** Receives Python's stdout and stderr lines (see _apple_support) and sends them to the system log. */
static PyObject *LogWrite(PyObject *self, PyObject *args)
{
  int level;
  const char *text;
  if (!PyArg_ParseTuple(args, "iy", &level, &text)) {
    return NULL;
  }
  os_log_with_type(kernelLog, (os_log_type_t)level, "%{public}s", text);
  Py_RETURN_NONE;
}

static PyMethodDef logWriteDef = {"log_write", LogWrite, METH_VARARGS, NULL};

static BOOL InitPython(NSError **error)
{
  NSString *resources = NSBundle.mainBundle.resourcePath;
  NSString *pycache = [NSSearchPathForDirectoriesInDomains(NSCachesDirectory, NSUserDomainMask, YES).firstObject
      stringByAppendingPathComponent:@"cow-pycache"];

  PyPreConfig preconfig;
  PyPreConfig_InitIsolatedConfig(&preconfig);
  preconfig.utf8_mode = 1;
  PyStatus status = Py_PreInitialize(&preconfig);
  if (PyStatus_Exception(status)) {
    *error = KernelError([NSString stringWithFormat:@"Python pre-init failed: %s", status.err_msg]);
    return NO;
  }

  PyConfig config;
  PyConfig_InitIsolatedConfig(&config);
  config.buffered_stdio = 0;
  config.install_signal_handlers = 0;
  // The bundle is read-only, so compiled modules are cached outside it.
  config.write_bytecode = 1;
  status = PyConfig_SetBytesString(&config, &config.pycache_prefix, pycache.UTF8String);
  if (!PyStatus_Exception(status)) {
    NSString *pythonHome = [resources stringByAppendingPathComponent:@"python"];
    status = PyConfig_SetBytesString(&config, &config.home, pythonHome.UTF8String);
  }
  if (!PyStatus_Exception(status)) {
    status = PyConfig_Read(&config);
  }
  if (!PyStatus_Exception(status)) {
    status = Py_InitializeFromConfig(&config);
  }
  PyConfig_Clear(&config);
  if (PyStatus_Exception(status)) {
    *error = KernelError([NSString stringWithFormat:@"Python init failed: %s", status.err_msg]);
    return NO;
  }

  PyObject *logWrite = PyCFunction_New(&logWriteDef, NULL);
  PyObject *support = PyImport_ImportModule("_apple_support");
  PyObject *ok = support && logWrite
      ? PyObject_CallMethod(support, "init_streams", "Oii", logWrite, OS_LOG_TYPE_DEFAULT, OS_LOG_TYPE_ERROR)
      : NULL;
  if (!ok) {
    PyErr_Clear();
  }
  Py_XDECREF(ok);
  Py_XDECREF(support);
  Py_XDECREF(logWrite);

  NSString *packages = [resources stringByAppendingPathComponent:@"python/app_packages"];
  PyObject *site = PyImport_ImportModule("site");
  PyObject *added = site ? PyObject_CallMethod(site, "addsitedir", "s", packages.UTF8String) : NULL;
  if (!added) {
    // The kernel's own imports then fail with the details.
    PyErr_Print();
  }
  Py_XDECREF(added);
  Py_XDECREF(site);

  // Background threads take the GIL through PyGILState_Ensure from here on.
  PyEval_SaveThread();
  return YES;
}

static BOOL SetEnviron(PyObject *environ, NSDictionary<NSString *, NSString *> *values)
{
  for (NSString *key in values) {
    PyObject *value = PyUnicode_FromString(values[key].UTF8String);
    int failed = !value || PyMapping_SetItemString(environ, key.UTF8String, value) < 0;
    Py_XDECREF(value);
    if (failed) {
      return NO;
    }
  }
  return YES;
}

/** Point the kernel at its data and run app.run(), which blocks while the kernel serves. */
static void RunKernel(NSString *sources, NSString *home, NSDictionary<NSString *, NSString *> *env)
{
  PyGILState_STATE gil = PyGILState_Ensure();
  PyObject *os = PyImport_ImportModule("os");
  PyObject *environ = os ? PyObject_GetAttrString(os, "environ") : NULL;
  PyObject *sysPath = PySys_GetObject("path");
  PyObject *sourcesPath = PyUnicode_FromString(sources.UTF8String);
  BOOL ready = environ && SetEnviron(environ, env) && sysPath && sourcesPath;
  if (ready) {
    int present = PySequence_Contains(sysPath, sourcesPath);
    ready = present == 1 || (present == 0 && PyList_Insert(sysPath, 0, sourcesPath) == 0);
  }
  PyObject *chdir = ready ? PyObject_CallMethod(os, "chdir", "s", home.UTF8String) : NULL;
  PyObject *app = chdir ? PyImport_ImportModule("app") : NULL;
  PyObject *result = app ? PyObject_CallMethod(app, "run", NULL) : NULL;
  if (!result) {
    PyErr_Print();
  }
  Py_XDECREF(result);
  Py_XDECREF(app);
  Py_XDECREF(chdir);
  Py_XDECREF(sourcesPath);
  Py_XDECREF(environ);
  Py_XDECREF(os);
  PyGILState_Release(gil);
}

static NSDictionary *StartKernel(NSError **error)
{
  @synchronized([NSProcessInfo class]) {
    if (endpoint && running) {
      return endpoint;
    }

    NSUserDefaults *prefs = NSUserDefaults.standardUserDefaults;
    // The console password guards the port against other apps on this device,
    // which can reach loopback too. It never leaves the app.
    NSString *password = [prefs stringForKey:kPasswordKey];
    if (!password) {
      password = NewSecret();
      if (!password) {
        *error = KernelError(@"Could not generate the console password");
        return nil;
      }
      [prefs setObject:password forKey:kPasswordKey];
    }
    int port = PickPort((int)[prefs integerForKey:kPortKey]);
    if (port <= 0) {
      *error = KernelError(@"No free loopback port");
      return nil;
    }
    [prefs setInteger:port forKey:kPortKey];

    // The kernel keeps its workspace under ~/cow, like on a desktop.
    NSString *home = NSSearchPathForDirectoriesInDomains(NSApplicationSupportDirectory, NSUserDomainMask, YES).firstObject;
    if (![NSFileManager.defaultManager createDirectoryAtPath:home withIntermediateDirectories:YES attributes:nil error:error]) {
      return nil;
    }
    NSString *sources = InstallSources(home, prefs, error);
    if (!sources) {
      return nil;
    }
    NSString *certs = [NSBundle.mainBundle.resourcePath
        stringByAppendingPathComponent:@"python/app_packages/certifi/cacert.pem"];
    NSMutableDictionary *env = [@{
      @"HOME" : home,
      @"TMPDIR" : NSTemporaryDirectory(),
      // OpenSSL finds no CA store on iOS; urllib-based HTTPS needs one.
      @"SSL_CERT_FILE" : certs,
      @"COW_DEPLOYMENT" : @"mobile",
      @"COW_DATA_DIR" : [home stringByAppendingPathComponent:@".cow"],
      @"COW_WEB_PORT" : [NSString stringWithFormat:@"%d", port],
      @"WEB_PASSWORD" : password,
    } mutableCopy];
    // First launch only: later the app's Settings owns cow_lang via the API.
    // Blank (ignored by the kernel) otherwise, as a restart keeps os.environ.
    NSString *configPath = [home stringByAppendingPathComponent:@".cow/config.json"];
    BOOL firstRun = ![NSFileManager.defaultManager fileExistsAtPath:configPath];
    NSString *preferred = NSLocale.preferredLanguages.firstObject.lowercaseString ?: @"";
    env[@"COW_LANG"] = !firstRun ? @"" : [preferred hasPrefix:@"zh"] ? @"zh" : @"en";

    NSThread *thread = [[NSThread alloc] initWithBlock:^{
      NSError *initError = nil;
      if (!pythonReady && !(pythonReady = InitPython(&initError))) {
        os_log_error(kernelLog, "kernel did not start: %{public}@", initError.localizedDescription);
      } else {
        RunKernel(sources, home, env);
        os_log_error(kernelLog, "kernel stopped");
      }
      @synchronized([NSProcessInfo class]) {
        running = NO;
      }
    }];
    thread.name = @"cow-kernel";
    // Python's own threads get 16 MB on Apple platforms; the 512 KB default is too small.
    thread.stackSize = 16 << 20;
    running = YES;
    [thread start];
    endpoint = @{@"port" : @(port), @"password" : password};
    return endpoint;
  }
}

@interface CowKernel : NSObject <RCTBridgeModule>
@end

@implementation CowKernel

RCT_EXPORT_MODULE()

+ (void)initialize
{
  kernelLog = os_log_create("ai.cowagent.app", "kernel");
}

+ (BOOL)requiresMainQueueSetup
{
  return NO;
}

- (dispatch_queue_t)methodQueue
{
  // Unpacking the sources takes a moment on first launch; keep it off the JS and main threads.
  static dispatch_queue_t queue;
  static dispatch_once_t once;
  dispatch_once(&once, ^{
    queue = dispatch_queue_create("ai.cowagent.kernel", DISPATCH_QUEUE_SERIAL);
  });
  return queue;
}

/** Resolves with `{port, password}` once the kernel thread is started; it binds shortly after. */
RCT_EXPORT_METHOD(start : (RCTPromiseResolveBlock)resolve reject : (RCTPromiseRejectBlock)reject)
{
  NSError *error = nil;
  NSDictionary *started = StartKernel(&error);
  if (started) {
    resolve(started);
  } else {
    reject(@"kernel_start_failed", error.localizedDescription, error);
  }
}

@end
