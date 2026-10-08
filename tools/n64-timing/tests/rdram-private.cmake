# unit:rdram-private (checks.tsv). Builds the two variants of rdram-private.cpp:
# the Loader control must compile, the device read must fail on the access check.
# usage: cmake -DBUILD_DIR=<build dir> -P rdram-private.cmake
foreach(variant friend device)
  execute_process(
    COMMAND ${CMAKE_COMMAND} --build ${BUILD_DIR} --target n64-timing-rdram-${variant}
    RESULT_VARIABLE result_${variant}
    OUTPUT_VARIABLE output_${variant}
    ERROR_VARIABLE output_${variant})
endforeach()
if(NOT result_friend EQUAL 0)
  message(FATAL_ERROR "rdram-private: the Loader control failed to compile, so the probe proves nothing:\n${output_friend}")
endif()
if(result_device EQUAL 0)
  message(FATAL_ERROR "rdram-private: a device-side read of rdram.ram compiled; RDRAM data is no longer private to the RI")
endif()
# clang: "'ram' is a private member"; gcc: "'...::RDRAM::ram' is private within this context" (quotes vary by locale).
if(NOT output_device MATCHES "'ram' is a private member|RDRAM::ram[^ ]* is private within this context")
  message(FATAL_ERROR "rdram-private: the device read failed for another reason:\n${output_device}")
endif()
message("rdram-private: ok")
