cmake_minimum_required(VERSION 3.20)
project(etp_core VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

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

# Sanitizers in Debug mode (GCC / Clang)
if(CMAKE_BUILD_TYPE STREQUAL "Debug" AND NOT MSVC)
    target_compile_options(etp_core PRIVATE -fsanitize=address,leak,undefined -g)
    target_link_options(etp_core PRIVATE -fsanitize=address,leak,undefined)
    target_compile_options(test_etp_core PRIVATE -fsanitize=address,leak,undefined -g)
    target_link_options(test_etp_core PRIVATE -fsanitize=address,leak,undefined)
endif()

# Optional pybind11 module target
find_package(pybind11 CONFIG QUIET)
if(pybind11_FOUND)
    pybind11_add_module(etp_core_cpp src/pybind_bindings.cpp ${SOURCES})
    target_link_libraries(etp_core_cpp PRIVATE OpenSSL::Crypto OpenSSL::SSL)
    message(STATUS "pybind11 found: etp_core_cpp python module target added.")
else()
    message(STATUS "pybind11 not found: skipping etp_core_cpp target.")
endif()
