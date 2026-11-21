cmake_minimum_required(VERSION 3.11)
project(rnapp)

set(RNOH_APP_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
set(NODE_MODULES "${CMAKE_CURRENT_SOURCE_DIR}/../../../../../node_modules")
set(RNOH_CPP_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../../../oh_modules/@rnoh/react-native-openharmony/src/main/cpp")
set(RNOH_GENERATED_DIR "${CMAKE_CURRENT_SOURCE_DIR}/generated")
set(LOG_VERBOSITY_LEVEL 1)
set(CMAKE_ASM_FLAGS "-Wno-error=unused-command-line-argument -Qunused-arguments")
set(CMAKE_CXX_FLAGS "-fstack-protector-strong -Wl,-z,relro,-z,now,-z,noexecstack -s -fPIE -pie")
set(WITH_HITRACE_SYSTRACE ON)
set(WITH_HITRACE_REACT_MARKER ON)
set(OH_MODULES_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../../../oh_modules") # required by 'autolink_libraries'
set(OH_MODULES "${OH_MODULES_DIR}") # gesture-handler looks up react-native-svg through this name

add_subdirectory("${RNOH_CPP_DIR}" ./rn)

include("${CMAKE_CURRENT_SOURCE_DIR}/autolinking.cmake")

# Libraries without autolinking metadata. worklets must precede reanimated,
# which links against the rnoh_worklets target.
add_subdirectory("${OH_MODULES_DIR}/@react-native-ohos/react-native-worklets/src/main/cpp" ./rnoh_worklets)
add_subdirectory("${OH_MODULES_DIR}/@react-native-ohos/react-native-reanimated/src/main/cpp" ./rnoh_reanimated)
add_subdirectory("${OH_MODULES_DIR}/@react-native-ohos/react-native-gesture-handler/src/main/cpp" ./rnoh_gesture_handler)
add_subdirectory("${OH_MODULES_DIR}/@react-native-ohos/react-native-screens/src/main/cpp" ./rnoh_screens)
add_subdirectory("${OH_MODULES_DIR}/@react-native-ohos/react-native-svg/src/main/cpp" ./rnoh_svg)

file(GLOB GENERATED_CPP_FILES "${CMAKE_CURRENT_SOURCE_DIR}/generated/*.cpp") # this line is needed by codegen v1
add_library(rnoh_app SHARED
    ${GENERATED_CPP_FILES}
    "./PackageProvider.cpp"
    "${RNOH_CPP_DIR}/RNOHAppNapiBridge.cpp"
)
target_link_libraries(rnoh_app PUBLIC rnoh)

autolink_libraries(rnoh_app)
target_link_libraries(rnoh_app PUBLIC
    rnoh_worklets
    rnoh_reanimated
    rnoh_gesture_handler
    rnoh_screens
    rnoh_svg
)

# The embedded agent kernel. Without the runtime from mobile/kernel/harmony_prepare.py
# for this ABI it builds as a stub, and the app offers remote servers only.
set(COW_PYTHON_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../../../cow-python/${OHOS_ARCH}")
add_library(cowkernel SHARED "./kernel/CowKernel.cpp")
set_target_properties(cowkernel PROPERTIES CXX_STANDARD 17 CXX_STANDARD_REQUIRED ON)
target_link_libraries(cowkernel PRIVATE libace_napi.z.so)
if(EXISTS "${COW_PYTHON_DIR}/lib/libcowpython.a")
    message(STATUS "cowkernel: embedding Python from ${COW_PYTHON_DIR}")
    target_compile_definitions(cowkernel PRIVATE COW_KERNEL_PYTHON=1)
    target_include_directories(cowkernel PRIVATE "${COW_PYTHON_DIR}/include/python3.13")
    target_link_libraries(cowkernel PRIVATE "${COW_PYTHON_DIR}/lib/libcowpython.a" libhilog_ndk.z.so z m)
else()
    message(STATUS "cowkernel: no Python runtime for ${OHOS_ARCH}, building the stub")
endif()
