/*
 * libcowkernel.so: runs the CowAgent Python backend inside this app (see
 * ets/native/CowKernelModule.ets, which prepares the files and environment).
 *
 * CPython and every extension module the kernel needs are linked in statically
 * (mobile/kernel/harmony_prepare.py builds them), because app data is mounted
 * noexec and Python could not load extension modules from there. Builds made
 * without that runtime compile to a stub whose available() is false, and the
 * app then offers remote servers only.
 *
 * The kernel is process-wide rather than per React instance, so a JS reload
 * finds the kernel that is already running instead of starting a second one.
 */

#include <arpa/inet.h>
#include <napi/native_api.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

#include <map>
#include <mutex>
#include <string>
#include <vector>

#ifdef COW_KERNEL_PYTHON
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <hilog/log.h>
#include <pthread.h>

// The regex package's extension module, linked in from libcowpython.a.
extern "C" PyObject* PyInit__regex(void);
#endif

namespace {

/** Bind 127.0.0.1:port (0 = any free port) and return the bound port, or 0 on failure. */
int TryBind(int port) {
  int fd = socket(AF_INET, SOCK_STREAM, 0);
  if (fd < 0) {
    return 0;
  }
  sockaddr_in addr = {};
  addr.sin_family = AF_INET;
  addr.sin_port = htons(static_cast<uint16_t>(port));
  addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  socklen_t len = sizeof(addr);
  int bound = 0;
  if (bind(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == 0 &&
      getsockname(fd, reinterpret_cast<sockaddr*>(&addr), &len) == 0) {
    bound = ntohs(addr.sin_port);
  }
  close(fd);
  return bound;
}

std::string GetString(napi_env env, napi_value value) {
  size_t len = 0;
  if (napi_get_value_string_utf8(env, value, nullptr, 0, &len) != napi_ok) {
    return "";
  }
  std::string out(len, '\0');
  napi_get_value_string_utf8(env, value, out.data(), len + 1, &len);
  return out;
}

std::string GetStringProperty(napi_env env, napi_value object, const char* name) {
  napi_value value;
  return napi_get_named_property(env, object, name, &value) == napi_ok ? GetString(env, value) : "";
}

std::vector<std::string> GetStringArray(napi_env env, napi_value object, const char* name) {
  std::vector<std::string> out;
  napi_value array;
  uint32_t count = 0;
  if (napi_get_named_property(env, object, name, &array) != napi_ok ||
      napi_get_array_length(env, array, &count) != napi_ok) {
    return out;
  }
  for (uint32_t i = 0; i < count; i++) {
    napi_value item;
    napi_get_element(env, array, i, &item);
    out.push_back(GetString(env, item));
  }
  return out;
}

std::map<std::string, std::string> GetStringMap(napi_env env, napi_value object, const char* name) {
  std::map<std::string, std::string> out;
  napi_value map;
  napi_value keys;
  uint32_t count = 0;
  if (napi_get_named_property(env, object, name, &map) != napi_ok ||
      napi_get_property_names(env, map, &keys) != napi_ok ||
      napi_get_array_length(env, keys, &count) != napi_ok) {
    return out;
  }
  for (uint32_t i = 0; i < count; i++) {
    napi_value key;
    napi_value value;
    napi_get_element(env, keys, i, &key);
    napi_get_property(env, map, key, &value);
    out[GetString(env, key)] = GetString(env, value);
  }
  return out;
}

#ifdef COW_KERNEL_PYTHON

constexpr unsigned int kLogDomain = 0x0C0E;
constexpr const char* kLogTag = "CowKernel";
// Python's own threads get 16 MB on Apple platforms; musl's 128 KB default is far too small.
constexpr size_t kStackSize = 16 << 20;

struct KernelConfig {
  std::string pythonHome;
  std::vector<std::string> pythonPath;
  std::string pycache;
  std::string sources;
  std::string home;
  std::map<std::string, std::string> env;
};

std::mutex stateMutex;
bool pythonReady = false;
bool running = false;

/**
 * Receives Python's stdout and stderr lines and sends them to hilog. The kernel
 * logs bits of conversations, so they stay private: `hilog -p off` shows them.
 */
PyObject* LogWrite(PyObject*, PyObject* args) {
  int level;
  const char* text;
  if (!PyArg_ParseTuple(args, "is", &level, &text)) {
    return nullptr;
  }
  OH_LOG_Print(LOG_APP, static_cast<LogLevel>(level), kLogDomain, kLogTag, "%{private}s", text);
  Py_RETURN_NONE;
}

PyMethodDef logMethods[] = {
    {"write", LogWrite, METH_VARARGS, nullptr},
    {nullptr, nullptr, 0, nullptr},
};

PyModuleDef logModule = {PyModuleDef_HEAD_INIT, "_cowlog", nullptr, -1, logMethods};

PyObject* InitLogModule() {
  return PyModule_Create(&logModule);
}

// Line-buffers sys.stdout and sys.stderr into _cowlog, as hilog takes whole lines.
constexpr const char* kStreamsSource = R"PY(
import io, sys, _cowlog

class _LogStream(io.TextIOBase):
    def __init__(self, level):
        self._level = level
        self._pending = ''

    def writable(self):
        return True

    def write(self, text):
        lines = (self._pending + text).split('\n')
        self._pending = lines.pop()
        for line in lines:
            _cowlog.write(self._level, line)
        return len(text)

    def flush(self):
        if self._pending:
            _cowlog.write(self._level, self._pending)
            self._pending = ''

sys.stdout = _LogStream(4)
sys.stderr = _LogStream(6)
)PY";

void LogError(const std::string& message) {
  OH_LOG_Print(LOG_APP, LOG_ERROR, kLogDomain, kLogTag, "%{public}s", message.c_str());
}

bool InitPython(const KernelConfig& config) {
  PyPreConfig preconfig;
  PyPreConfig_InitIsolatedConfig(&preconfig);
  preconfig.utf8_mode = 1;
  PyStatus status = Py_PreInitialize(&preconfig);
  if (PyStatus_Exception(status)) {
    LogError(std::string("Python pre-init failed: ") + (status.err_msg ? status.err_msg : ""));
    return false;
  }

  PyImport_AppendInittab("_cowlog", InitLogModule);
  PyImport_AppendInittab("regex._regex", PyInit__regex);

  PyConfig pyconfig;
  PyConfig_InitIsolatedConfig(&pyconfig);
  pyconfig.buffered_stdio = 0;
  pyconfig.install_signal_handlers = 0;
  pyconfig.site_import = 0;
  // The kernel sources are plain .py files; their bytecode is cached outside them.
  pyconfig.write_bytecode = 1;
  status = PyConfig_SetBytesString(&pyconfig, &pyconfig.pycache_prefix, config.pycache.c_str());
  if (!PyStatus_Exception(status)) {
    status = PyConfig_SetBytesString(&pyconfig, &pyconfig.home, config.pythonHome.c_str());
  }
  pyconfig.module_search_paths_set = 1;
  for (const auto& path : config.pythonPath) {
    if (PyStatus_Exception(status)) {
      break;
    }
    wchar_t* wide = Py_DecodeLocale(path.c_str(), nullptr);
    if (!wide) {
      status = PyStatus_NoMemory();
      break;
    }
    status = PyWideStringList_Append(&pyconfig.module_search_paths, wide);
    PyMem_RawFree(wide);
  }
  if (!PyStatus_Exception(status)) {
    status = Py_InitializeFromConfig(&pyconfig);
  }
  PyConfig_Clear(&pyconfig);
  if (PyStatus_Exception(status)) {
    LogError(std::string("Python init failed: ") + (status.err_msg ? status.err_msg : ""));
    return false;
  }
  if (PyRun_SimpleString(kStreamsSource) != 0) {
    LogError("Could not redirect Python output to hilog");
  }
  // RunKernel takes the GIL through PyGILState_Ensure from here on.
  PyEval_SaveThread();
  return true;
}

bool SetEnviron(PyObject* environ, const std::map<std::string, std::string>& values) {
  for (const auto& [key, text] : values) {
    PyObject* value = PyUnicode_FromString(text.c_str());
    bool failed = !value || PyMapping_SetItemString(environ, key.c_str(), value) < 0;
    Py_XDECREF(value);
    if (failed) {
      return false;
    }
  }
  return true;
}

/** Point the kernel at its data and run app.run(), which blocks while the kernel serves. */
void RunKernel(const KernelConfig& config) {
  PyGILState_STATE gil = PyGILState_Ensure();
  PyObject* os = PyImport_ImportModule("os");
  PyObject* environ = os ? PyObject_GetAttrString(os, "environ") : nullptr;
  PyObject* sysPath = PySys_GetObject("path");
  PyObject* sourcesPath = PyUnicode_FromString(config.sources.c_str());
  bool ready = environ && SetEnviron(environ, config.env) && sysPath && sourcesPath;
  if (ready) {
    int present = PySequence_Contains(sysPath, sourcesPath);
    ready = present == 1 || (present == 0 && PyList_Insert(sysPath, 0, sourcesPath) == 0);
  }
  PyObject* chdir = ready ? PyObject_CallMethod(os, "chdir", "s", config.home.c_str()) : nullptr;
  PyObject* app = chdir ? PyImport_ImportModule("app") : nullptr;
  PyObject* result = app ? PyObject_CallMethod(app, "run", nullptr) : nullptr;
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

void* KernelThread(void* arg) {
  KernelConfig* config = static_cast<KernelConfig*>(arg);
  bool ready;
  {
    std::lock_guard<std::mutex> lock(stateMutex);
    ready = pythonReady;
  }
  if (!ready && InitPython(*config)) {
    std::lock_guard<std::mutex> lock(stateMutex);
    pythonReady = ready = true;
  }
  if (ready) {
    RunKernel(*config);
    LogError("kernel stopped");
  } else {
    LogError("kernel did not start");
  }
  delete config;
  std::lock_guard<std::mutex> lock(stateMutex);
  running = false;
  return nullptr;
}

/** Starts the kernel thread; false when it is already running. */
bool StartKernel(KernelConfig* config, std::string* error) {
  std::lock_guard<std::mutex> lock(stateMutex);
  if (running) {
    delete config;
    return false;
  }
  pthread_attr_t attr;
  pthread_attr_init(&attr);
  pthread_attr_setstacksize(&attr, kStackSize);
  pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
  pthread_t thread;
  int failed = pthread_create(&thread, &attr, KernelThread, config);
  pthread_attr_destroy(&attr);
  if (failed) {
    delete config;
    *error = "Could not start the kernel thread";
    return false;
  }
  pthread_setname_np(thread, "cow-kernel");
  running = true;
  return true;
}

#endif  // COW_KERNEL_PYTHON

napi_value Available(napi_env env, napi_callback_info) {
  napi_value result;
#ifdef COW_KERNEL_PYTHON
  napi_get_boolean(env, true, &result);
#else
  napi_get_boolean(env, false, &result);
#endif
  return result;
}

napi_value IsRunning(napi_env env, napi_callback_info) {
  bool value = false;
#ifdef COW_KERNEL_PYTHON
  std::lock_guard<std::mutex> lock(stateMutex);
  value = running;
#endif
  napi_value result;
  napi_get_boolean(env, value, &result);
  return result;
}

/** pickPort(preferred): the last port if it is still free, so the saved server address keeps working. */
napi_value PickPort(napi_env env, napi_callback_info info) {
  size_t argc = 1;
  napi_value argv[1];
  napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);
  int32_t preferred = 0;
  if (argc > 0) {
    napi_get_value_int32(env, argv[0], &preferred);
  }
  int port = preferred > 0 ? TryBind(preferred) : 0;
  if (port <= 0) {
    port = TryBind(0);
  }
  napi_value result;
  napi_create_int32(env, port, &result);
  return result;
}

/** start(config): see KernelConfig in libcowkernel's index.d.ts. False when already running. */
napi_value Start(napi_env env, napi_callback_info info) {
  size_t argc = 1;
  napi_value argv[1];
  napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);
#ifdef COW_KERNEL_PYTHON
  if (argc < 1) {
    napi_throw_error(env, nullptr, "start() needs a config");
    return nullptr;
  }
  auto* config = new KernelConfig{
      GetStringProperty(env, argv[0], "pythonHome"),
      GetStringArray(env, argv[0], "pythonPath"),
      GetStringProperty(env, argv[0], "pycache"),
      GetStringProperty(env, argv[0], "sources"),
      GetStringProperty(env, argv[0], "home"),
      GetStringMap(env, argv[0], "env"),
  };
  std::string error;
  bool started = StartKernel(config, &error);
  if (!error.empty()) {
    napi_throw_error(env, nullptr, error.c_str());
    return nullptr;
  }
  napi_value result;
  napi_get_boolean(env, started, &result);
  return result;
#else
  napi_throw_error(env, nullptr, "This build has no embedded kernel");
  return nullptr;
#endif
}

napi_value Init(napi_env env, napi_value exports) {
  napi_property_descriptor desc[] = {
      {"available", nullptr, Available, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"isRunning", nullptr, IsRunning, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"pickPort", nullptr, PickPort, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"start", nullptr, Start, nullptr, nullptr, nullptr, napi_default, nullptr},
  };
  napi_define_properties(env, exports, sizeof(desc) / sizeof(desc[0]), desc);
  return exports;
}

napi_module cowKernelModule = {
    .nm_version = 1,
    .nm_flags = 0,
    .nm_filename = nullptr,
    .nm_register_func = Init,
    .nm_modname = "cowkernel",
    .nm_priv = nullptr,
    .reserved = {nullptr},
};

}  // namespace

extern "C" __attribute__((constructor)) void RegisterCowKernelModule() {
  napi_module_register(&cowKernelModule);
}
