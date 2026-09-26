cmake_minimum_required(VERSION 3.20)
project(etp_core VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# Compiler warning flags
if(MSVC)
    add_compile_options(/W4)
else()
    add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# Find OpenSSL 3.0
find_package(OpenSSL 3.0 REQUIRED)

# Include directories
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/include ${OPENSSL_INCLUDE_DIR})

# Source files
set(SOURCES
    src/route_mutator.cpp
    src/gateway.cpp
    src/merkle.cpp
)

# Native library target
add_library(etp_core SHARED ${SOURCES})
target_link_libraries(etp_core PRIVATE OpenSSL::Crypto OpenSSL::SSL)

# Native C++ test executable
add_executable(test_etp_core tests/test_etp_core.cpp ${SOURCES})
target_link_libraries(test_etp_core PRIVATE OpenSSL::Crypto OpenSSL::SSL)

# Benchmark executable
option(BUILD_BENCHMARKS "Build benchmark executables" ON)
if(BUILD_BENCHMARKS AND EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/bench/bench_etp_core.cpp")
    add_executable(bench_etp_core bench/bench_etp_core.cpp ${SOURCES})
    target_link_libraries(bench_etp_core PRIVATE OpenSSL::Crypto OpenSSL::SSL)
endif()

# Fuzzing target (Clang libFuzzer option)
option(BUILD_FUZZERS "Build libFuzzer fuzzing binaries" OFF)
if(BUILD_FUZZERS AND EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/fuzz/fuzz_gateway.cpp")
    add_executable(fuzz_gateway fuzz/fuzz_gateway.cpp ${SOURCES})
    target_compile_options(fuzz_gateway PRIVATE -fsanitize=fuzzer,address,undefined)
    target_link_options(fuzz_gateway PRIVATE -fsanitize=fuzzer,address,undefined)
    target_link_libraries(fuzz_gateway PRIVATE OpenSSL::Crypto OpenSSL::SSL)
endif()

# Pybind11 module target
option(BUILD_PYTHON_BINDINGS "Build pybind11 Python extension module" ON)
if(BUILD_PYTHON_BINDINGS)
    find_package(pybind11 CONFIG QUIET)
    if(NOT pybind11_FOUND)
        # Attempt finding pybind11 via Python module if pybind11_DIR wasn't provided
        find_package(pybind11 CONFIG REQUIRED)
    endif()
    if(pybind11_FOUND)
        pybind11_add_module(etp_core_cpp src/pybind_bindings.cpp ${SOURCES})
        target_link_libraries(etp_core_cpp PRIVATE OpenSSL::Crypto OpenSSL::SSL)
        message(STATUS "pybind11 found: etp_core_cpp python module target added.")
    endif()
endif()

# Sanitizers in Debug mode (GCC / Clang) across all targets
if(CMAKE_BUILD_TYPE STREQUAL "Debug" AND NOT MSVC)
    target_compile_options(etp_core PRIVATE -fsanitize=address,leak,undefined -g)
    target_link_options(etp_core PRIVATE -fsanitize=address,leak,undefined)
    target_compile_options(test_etp_core PRIVATE -fsanitize=address,leak,undefined -g)
    target_link_options(test_etp_core PRIVATE -fsanitize=address,leak,undefined)
    if(TARGET bench_etp_core)
        target_compile_options(bench_etp_core PRIVATE -fsanitize=address,leak,undefined -g)
        target_link_options(bench_etp_core PRIVATE -fsanitize=address,leak,undefined)
    endif()
    if(TARGET etp_core_cpp)
        target_compile_options(etp_core_cpp PRIVATE -fsanitize=address,leak,undefined -g)
        target_link_options(etp_core_cpp PRIVATE -fsanitize=address,leak,undefined)
    endif()
endif()

# Installation targets for OEM C++ SDK packaging
include(GNUInstallDirs)
install(TARGETS etp_core DESTINATION ${CMAKE_INSTALL_LIBDIR})
install(DIRECTORY include/etp DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})

