ares_components(sm5k)

ares_add_sources(
  CORE #
    n64
  UNITY #
    n64.cpp
  PRIMARY #
    memory/memory.cpp
    system/system.cpp
    cartridge/cartridge.cpp
    cic/cic.cpp
    controller/controller.cpp
    dd/dd.cpp
    mi/mi.cpp
    vi/vi.cpp
    ai/ai.cpp
    pi/pi.cpp
    pif/pif.cpp
    ri/ri.cpp
    si/si.cpp
    rdram/rdram.cpp
    cpu/cpu.cpp
    rsp/rsp.cpp
    rdp/rdp.cpp
    aleck64/aleck64.cpp
    timing/timeline.cpp
    timing/verify.cpp
)

if(OS_WINDOWS)
  include(cmake/os-windows.cmake)
elseif(OS_MACOS)
  include(cmake/os-macos.cmake)
elseif(OS_LINUX OR OS_FREEBSD OR OS_OPENBSD)
  include(cmake/os-linux.cmake)
endif()

ares_add_sources(
  CORE #
    n64
  INCLUDED #
    n64.hpp
    accuracy.hpp
    CMakeLists.txt
)

ares_add_sources(
  CORE #
    n64
  INCLUDED #
    ai/ai.hpp
    ai/debugger.cpp
    ai/io.cpp
    ai/serialization.cpp
)

ares_add_sources(
  CORE #
    n64
  INCLUDED #
    aleck64/aleck64.hpp
    aleck64/controls.cpp
    aleck64/debugger.cpp
    aleck64/serialization.cpp
    aleck64/io.cpp
    aleck64/vdp.cpp
    aleck64/game-config/11beat.hpp
    aleck64/game-config/doncdoon.hpp
    aleck64/game-config/kurufev.hpp
    aleck64/game-config/mayjin3.hpp
    aleck64/game-config/starsldr.hpp
    aleck64/game-config/twrshaft.hpp
    aleck64/game-config/vivdolls.hpp
    aleck64/game-config/hipai.hpp
    aleck64/game-config/hipai2.hpp
    aleck64/game-config/srmvs.hpp
    aleck64/game-config/mtetrisc.hpp
)

ares_add_sources(
  CORE #
    n64
  INCLUDED #
    cartridge/cartridge.hpp
    cartridge/debugger.cpp
    cartridge/flash.cpp
    cartridge/isviewer.cpp
    cartridge/joybus.cpp
    cartridge/rtc.cpp
    cartridge/serialization.cpp
    cartridge/slot.cpp
    cartridge/slot.hpp
)

ares_add_sources(
  CORE #
    n64
  INCLUDED #
    cic/cic.hpp
    cic/commands.cpp
    cic/io.cpp
    cic/serialization.cpp
)

ares_add_sources(
  CORE #
    n64
  INCLUDED #
    controller/controller.hpp
    controller/port.cpp
    controller/port.hpp
)

ares_add_sources(
  CORE #
    n64
  INCLUDED #
    controller/aleck64/aleck64.cpp
    controller/aleck64/aleck64.hpp
)

ares_add_sources(
  CORE #
    n64
  INCLUDED #
    controller/gamepad/bio-sensor.cpp
    controller/gamepad/gamepad.cpp
    controller/gamepad/gamepad.hpp
    controller/gamepad/transfer-pak.cpp
)

ares_add_sources(
  CORE #
    n64
  INCLUDED #
    controller/gamepad-gcn/gamepad-gcn.cpp
    controller/gamepad-gcn/gamepad-gcn.hpp
)

ares_add_sources(
  CORE #
    n64
  INCLUDED #
    controller/mouse/mouse.cpp
    controller/mouse/mouse.hpp
)

ares_add_sources(
  CORE #
    n64
  INCLUDED #
    cpu/algorithms.cpp
    cpu/context.cpp
    cpu/cpu.hpp
    cpu/dcache.cpp
    cpu/debugger.cpp
    cpu/disassembler.cpp
    cpu/exceptions.cpp
    cpu/interpreter-cop2.cpp
    cpu/interpreter-fpu.cpp
    cpu/interpreter-ipu.cpp
    cpu/interpreter-scc.cpp
    cpu/interpreter.cpp
    cpu/memory.cpp
    cpu/serialization.cpp
    cpu/tlb.cpp
)

ares_add_sources(
  CORE #
    n64
  INCLUDED #
    dd/controller.cpp
    dd/dd.hpp
    dd/debugger.cpp
    dd/drive.cpp
    dd/io.cpp
    dd/rtc.cpp
    dd/serialization.cpp
)

ares_add_sources(
  CORE #
    n64
  INCLUDED #
    memory/bus.hpp
    memory/io.hpp
    memory/memory.hpp
    memory/lsb/readable.hpp
    memory/lsb/writable.hpp
    memory/msb/readable.hpp
    memory/msb/writable.hpp
)

ares_add_sources(
  CORE #
    n64
  INCLUDED #
    mi/debugger.cpp
    mi/io.cpp
    mi/mi.hpp
    mi/serialization.cpp
)

ares_add_sources(
  CORE #
    n64
  INCLUDED #
    pi/bus.hpp
    pi/debugger.cpp
    pi/device.hpp
    pi/dma.cpp
    pi/io.cpp
    pi/pi.hpp
    pi/serialization.cpp
)

ares_add_sources(
  CORE #
    n64
  INCLUDED #
    pif/debugger.cpp
    pif/hle.cpp
    pif/io.cpp
    pif/pif.hpp
    pif/serialization.cpp
)

ares_add_sources(
  CORE #
    n64
  INCLUDED #
    rdp/debugger.cpp
    rdp/engine.cpp
    rdp/io.cpp
    rdp/rdp.hpp
    rdp/serialization.cpp
    rdp/timed.cpp
    rdp/timed.hpp
    rdp/engine/cen64_compat.h
    rdp/engine/rdp.h
    rdp/engine/rdp_blend.h
    rdp/engine/rdp_blendlut.h
    rdp/engine/rdp_core.h
    rdp/engine/rdp_poly.h
    rdp/engine/rdp_rgba.h
    rdp/engine/rdp_texpipe.h
    rdp/engine/rdp_types.h
    rdp/engine/rdp_wqueue.h
)

ares_add_sources(
  CORE #
    n64
  INCLUDED #
    rdram/debugger.cpp
    rdram/io.cpp
    rdram/rdram.hpp
    rdram/serialization.cpp
)

ares_add_sources(
  CORE #
    n64
  INCLUDED #
    ri/debugger.cpp
    ri/io.cpp
    ri/ri.hpp
    ri/serialization.cpp
)

ares_add_sources(
  CORE #
    n64
  INCLUDED #
    rsp/debugger.cpp
    rsp/decoder.cpp
    rsp/disassembler.cpp
    rsp/dma.cpp
    rsp/interpreter-ipu.cpp
    rsp/interpreter-scc.cpp
    rsp/interpreter-vpu.cpp
    rsp/interpreter.cpp
    rsp/io.cpp
    rsp/rsp.hpp
    rsp/serialization.cpp
)

ares_add_sources(
  CORE #
    n64
  INCLUDED #
    si/debugger.cpp
    si/dma.cpp
    si/io.cpp
    si/serialization.cpp
    si/si.hpp
)

ares_add_sources(
  CORE #
    n64
  INCLUDED #
    system/serialization.cpp
    system/system.hpp
)

ares_add_sources(
  CORE #
    n64
  INCLUDED #
    timing/behaviors.hpp
    timing/behaviors.tsv
    timing/clock.hpp
    timing/events.hpp
    timing/timeline.hpp
    timing/verify.hpp
)

find_package(Python3 REQUIRED COMPONENTS Interpreter)
add_custom_target(
  n64-timing-gen
  COMMAND Python3::Interpreter "${CMAKE_CURRENT_SOURCE_DIR}/../../tools/n64-timing/behaviors.py" --check
  COMMENT "Checking N64 timing behaviors, spec, check manifest and literal lint"
  VERBATIM
)
add_dependencies(ares n64-timing-gen)

ares_add_sources(
  CORE #
    n64
  INCLUDED #
    vi/debugger.cpp
    vi/io.cpp
    vi/serialization.cpp
    vi/vi.hpp
)

# cen64-jgemu pixel engine (rdp/engine/README.md). C sources; one worker
# (the emulation thread) so rendering is deterministic.
set(
  _rdp_engine_sources
  rdp/engine/rdp.c
  rdp/engine/rdp_blend.c
  rdp/engine/rdp_core.c
  rdp/engine/rdp_poly.c
  rdp/engine/rdp_texpipe.c
  rdp/engine/rdp_wqueue.c
)
target_sources(ares PRIVATE ${_rdp_engine_sources})
set_source_files_properties(
  ${_rdp_engine_sources}
  PROPERTIES COMPILE_DEFINITIONS "RDP_WQ_THREADS=1"
)

set(THREADS_PREFER_PTHREAD_FLAG ON)
find_package(Threads REQUIRED)
target_link_libraries(ares PUBLIC Threads::Threads)

