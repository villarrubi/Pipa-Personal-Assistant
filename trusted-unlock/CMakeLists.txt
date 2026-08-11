cmake_minimum_required(VERSION 3.20)

project(PipaTrustedUnlock LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_library(
    PipaTrustedUnlock
    SHARED
    src/dllmain.cpp
    src/exports.cpp
    src/CredentialProvider.cpp
    src/PipaCredential.cpp
    src/PipaGuids.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/PipaTrustedUnlock.def
)

target_include_directories(
    PipaTrustedUnlock
    PRIVATE
    include
)

target_compile_definitions(
    PipaTrustedUnlock
    PRIVATE
    UNICODE
    _UNICODE
)

target_link_libraries(
    PipaTrustedUnlock
    PRIVATE
    ole32
    shlwapi
)

set_target_properties(
    PipaTrustedUnlock
    PROPERTIES
    OUTPUT_NAME "PipaTrustedUnlock"
)

add_executable(
    PipaProviderTest
    tests/provider_smoke_test.cpp
)