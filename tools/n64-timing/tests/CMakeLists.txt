# Host unit tests for the N64 timing core (checks.tsv rows with the `unit:` prefix).
# Each test is one executable registered with ctest under its check id.
add_executable(n64-timing-tests timeline.cpp ri.cpp)
target_include_directories(n64-timing-tests PRIVATE ${CMAKE_SOURCE_DIR} ${CMAKE_SOURCE_DIR}/ares)
target_link_libraries(n64-timing-tests PRIVATE ares::nall)
set(CONSOLE TRUE)
ares_configure_executable(n64-timing-tests)
set_target_properties(n64-timing-tests PROPERTIES FOLDER tests PREFIX "")
add_test(NAME unit:timeline COMMAND n64-timing-tests timeline)
add_test(NAME unit:ri-cost-table COMMAND n64-timing-tests ri-cost-table)
add_test(NAME unit:ri-split COMMAND n64-timing-tests ri-split)

add_executable(n64-timing-dpc-regs dpc-regs.cpp)
target_include_directories(n64-timing-dpc-regs PRIVATE ${CMAKE_SOURCE_DIR} ${CMAKE_SOURCE_DIR}/ares)
target_link_libraries(n64-timing-dpc-regs PRIVATE ares::nall)
ares_configure_executable(n64-timing-dpc-regs)
set_target_properties(n64-timing-dpc-regs PROPERTIES FOLDER tests PREFIX "")
add_test(NAME unit:dpc-regs COMMAND n64-timing-dpc-regs)
