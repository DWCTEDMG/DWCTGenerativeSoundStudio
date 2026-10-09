cmake_minimum_required(VERSION 3.25)
project(EdmgStudioJuceAudioHost VERSION 0.1.0 LANGUAGES CXX)

include(FetchContent)
if(JUCE_ROOT)
    cmake_path(CONVERT "${JUCE_ROOT}" TO_CMAKE_PATH_LIST juce_SOURCE_DIR)
    add_subdirectory("${juce_SOURCE_DIR}" "${CMAKE_BINARY_DIR}/juce")
else()
    FetchContent_Declare(
        juce
        GIT_REPOSITORY https://github.com/juce-framework/JUCE.git
        GIT_TAG 8.0.0
        GIT_SHALLOW TRUE)
    FetchContent_MakeAvailable(juce)
endif()

juce_add_console_app(EdmgStudio.JuceAudioHost PRODUCT_NAME "EdmgStudio.JuceAudioHost")
target_sources(EdmgStudio.JuceAudioHost PRIVATE src/main.cpp)
target_compile_features(EdmgStudio.JuceAudioHost PRIVATE cxx_std_17)
target_compile_definitions(EdmgStudio.JuceAudioHost PRIVATE JUCE_WEB_BROWSER=0 JUCE_USE_CURL=0)
target_link_libraries(EdmgStudio.JuceAudioHost PRIVATE juce::juce_audio_utils juce::juce_core)

install(TARGETS EdmgStudio.JuceAudioHost RUNTIME DESTINATION bin)
install(FILES ${juce_SOURCE_DIR}/LICENSE.md DESTINATION licenses RENAME JUCE-LICENSE.md)
