cmake_minimum_required(VERSION 3.25)
project(EdmgStudioVst3Host VERSION 1.0.0 LANGUAGES CXX)

include(FetchContent)
set(SMTG_ENABLE_VST3_PLUGIN_EXAMPLES OFF CACHE BOOL "" FORCE)
set(SMTG_ENABLE_VST3_HOSTING_EXAMPLES OFF CACHE BOOL "" FORCE)
set(SMTG_ENABLE_VSTGUI_SUPPORT OFF CACHE BOOL "" FORCE)
set(SMTG_RUN_VST_VALIDATOR OFF CACHE BOOL "" FORCE)
if(VST3_SDK_ROOT)
    set(vst3sdk_SOURCE_DIR "${VST3_SDK_ROOT}")
    add_subdirectory("${VST3_SDK_ROOT}" "${CMAKE_BINARY_DIR}/vst3sdk")
else()
    FetchContent_Declare(
        vst3sdk
        GIT_REPOSITORY https://github.com/steinbergmedia/vst3sdk.git
        GIT_TAG 3cdf9ca5d1f5b1b21e0a86832aa4abe55607bd96
        GIT_SHALLOW FALSE
        GIT_SUBMODULES base cmake pluginterfaces public.sdk
        GIT_SUBMODULES_RECURSE TRUE)
    FetchContent_MakeAvailable(vst3sdk)
endif()

set(EDMG_VST3_NATIVE_SOURCES
    src/main.cpp
    ${vst3sdk_SOURCE_DIR}/public.sdk/source/vst/hosting/eventlist.cpp
    ${vst3sdk_SOURCE_DIR}/public.sdk/source/vst/hosting/module_win32.cpp
    ${vst3sdk_SOURCE_DIR}/public.sdk/source/vst/hosting/parameterchanges.cpp
    ${vst3sdk_SOURCE_DIR}/public.sdk/source/vst/hosting/plugprovider.cpp)

function(edmg_add_vst3_executable target_name mode_definition)
    add_executable(${target_name} ${EDMG_VST3_NATIVE_SOURCES})
    target_compile_features(${target_name} PRIVATE cxx_std_17)
    target_compile_definitions(${target_name} PRIVATE
        UNICODE _UNICODE NOMINMAX WIN32_LEAN_AND_MEAN ${mode_definition})
    target_link_libraries(${target_name} PRIVATE sdk_hosting sdk_common)
endfunction()

edmg_add_vst3_executable(EdmgStudio.Vst3Host EDMG_VST3_HOST_EXECUTABLE)
edmg_add_vst3_executable(EdmgStudio.Vst3Scanner EDMG_VST3_SCANNER_EXECUTABLE)

install(TARGETS EdmgStudio.Vst3Host EdmgStudio.Vst3Scanner RUNTIME DESTINATION bin)
install(FILES ${vst3sdk_SOURCE_DIR}/LICENSE DESTINATION licenses RENAME VST3-SDK-LICENSE.txt)
