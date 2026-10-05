add_executable(n64-run n64-run.cpp)

# n64-run reads core state (VI registers, RDRAM, cycle counters) directly, so it compiles
# against the N64 core's private headers rather than a public interface.
target_include_directories(
  n64-run
  PRIVATE
    ${CMAKE_SOURCE_DIR}
    ${CMAKE_SOURCE_DIR}/ares
    ${CMAKE_SOURCE_DIR}/thirdparty
    ${CMAKE_SOURCE_DIR}/ares/n64/vulkan/parallel-rdp/parallel-rdp
    ${CMAKE_SOURCE_DIR}/ares/n64/vulkan/parallel-rdp/volk
    ${CMAKE_SOURCE_DIR}/ares/n64/vulkan/parallel-rdp/vulkan
    ${CMAKE_SOURCE_DIR}/ares/n64/vulkan/parallel-rdp/vulkan-headers/include
    ${CMAKE_SOURCE_DIR}/ares/n64/vulkan/parallel-rdp/util
)
target_compile_definitions(n64-run PRIVATE MIA_LIBRARY)
target_link_libraries(n64-run PRIVATE ares::ares ares::mia ares::nall)

set(CONSOLE TRUE)
ares_configure_executable(n64-run)
target_enable_subproject(n64-run "n64-run (headless N64 runner)")
set_target_properties(n64-run PROPERTIES FOLDER tools PREFIX "")
