//Host unit test for Timing::Timeline with scripted actors (checks.tsv: unit:timeline).
//Each case names the defect it detects. Exits nonzero on the first failure.

#include <nall/nall.hpp>
#include <nall/main.hpp>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <string>

namespace test {
  using namespace nall;
  #include <n64/timing/clock.hpp>
  #include <n64/timing/timeline.hpp>
}

using namespace test;
using namespace test::Timing;

struct Step { s64 at; ActorId id; u32 kind; };
static std::vector<Step> steps;
static Timeline timeline;
static u32 failures = 0;

#define CHECK(cond, ...) do { if(!(cond)) { failures++; std::printf("FAIL %s:%d: ", __FILE__, __LINE__); std::printf(__VA_ARGS__); std::printf("\n"); } } while(0)

static auto rank(ActorId id) -> u32 { return (u32)id; }

//An actor that steps at a fixed list of times. A step is logged with its start
//time. `nestAt` makes the step at that time call catchUp on its own behalf, the
//way the RSP does before a DPC access, at `nestTarget` when set (an access late
//in a long step) and at the step's own time otherwise. A Parked or Blocked one
//still reports its next time, so only the kind keeps it from being stepped.
struct Scripted : Actor {
  ActorId id;
  Readiness::Kind kind = Readiness::Kind::Runnable;
  std::vector<s64> times;
  u32 next = 0;
  s64 nestAt = -1;
  s64 nestTarget = -1;
  s64 wakeAt = -1;            //the step at this time makes `wakes` runnable, the way a DPC_END write wakes the RDP
  struct Scripted* wakes = nullptr;
  u32 runs = 0;

  auto readiness() const -> Readiness override {
    if(next >= times.size()) return Readiness::parked();
    return {kind, Clock{times[next]}};
  }

  auto run(Clock limit) -> void override {
    runs++;
    do {
      s64 at = times[next++];
      steps.push_back({at, id, 0});
      if(at == nestAt) timeline.catchUp({nestTarget >= 0 ? nestTarget : at}, id);
      if(at == wakeAt) wakes->kind = Readiness::Kind::Runnable, timeline.wake(wakes->id);
      if(next >= times.size() || Clock{times[next]} >= timeline.limit(limit)) break;
      timeline.record(Clock{times[next]}, id);
    } while(true);
  }
};

static Scripted* wakeByEvent = nullptr;

static auto fired(const Timeline::Event& event) -> void {
  steps.push_back({event.at.units, ActorId::Events, event.kind});
  //an event that posts another one: the RTC tick reposting itself from its own time
  if(event.kind == 7) timeline.schedule({timeline.now({-1}) + Clock{5}, 8});
  //an event whose handler makes an actor runnable before the next event
  if(event.kind == 11 && wakeByEvent) wakeByEvent->kind = Readiness::Kind::Runnable, timeline.wake(wakeByEvent->id);
}

static auto reset() -> void {
  steps.clear();
  timeline = {};
  timeline.reset(fired);
}

static auto sorted() -> bool {
  for(u32 i = 1; i < steps.size(); i++) {
    auto& a = steps[i - 1];
    auto& b = steps[i];
    if(a.at > b.at) return false;
    if(a.at == b.at && rank(a.id) > rank(b.id)) return false;
  }
  return true;
}

static auto dump() -> std::string {
  std::string s;
  for(auto& e : steps) s += "(" + std::to_string(e.at) + "," + std::to_string((u32)e.id) + "," + std::to_string(e.kind) + ")";
  return s;
}

static auto testTimeline() -> u32 {
  //Ordering invariant: every step and event before the target runs in (time, rank)
  //order, and nothing at or after the target runs. Defect: a scan that picks the
  //first runnable actor instead of the earliest.
  {
    reset();
    Scripted rsp{}; rsp.id = ActorId::RSP; rsp.times = {5, 20, 35, 60, 100, 120};
    Scripted rdp{}; rdp.id = ActorId::RDP; rdp.times = {10, 30, 50, 100};
    timeline.attach(ActorId::RSP, &rsp);
    timeline.attach(ActorId::RDP, &rdp);
    timeline.schedule({{40}, 1});
    timeline.schedule({{15}, 2});
    timeline.schedule({{100}, 3});
    timeline.catchUp({100}, ActorId::CPU);
    CHECK(sorted(), "steps out of (time, rank) order: %s", dump().c_str());
    CHECK(steps.size() == 12, "expected 12 steps up to and including t=100, got %zu: %s", steps.size(), dump().c_str());
    CHECK(steps.back().at == 100 && steps.back().id == ActorId::RSP, "last step should be RSP at 100: %s", dump().c_str());
    CHECK(timeline.horizon() == Clock{120}, "horizon after catch-up should be the next step (120), got %lld", (long long)timeline.horizon().units);
  }

  //Tie-breaks: at equal times the Events heap (rank 1) runs before the RDP (3)
  //before the RSP (4), and an actor at the caller's own time runs only if its
  //rank is below the caller's. Defect: `<=` in the argmin or a missing rank test.
  {
    reset();
    Scripted rsp{}; rsp.id = ActorId::RSP; rsp.times = {50};
    Scripted rdp{}; rdp.id = ActorId::RDP; rdp.times = {50};
    Scripted sysad{}; sysad.id = ActorId::SysAD; sysad.times = {50};
    timeline.attach(ActorId::RSP, &rsp);
    timeline.attach(ActorId::RDP, &rdp);
    timeline.attach(ActorId::SysAD, &sysad);
    timeline.schedule({{50}, 9});
    timeline.schedule({{50}, 4});
    timeline.catchUp({50}, ActorId::RDP);
    CHECK(steps.size() == 3, "caller RDP at 50: Events(4), Events(9), SysAD run; RDP and RSP wait: %s", dump().c_str());
    CHECK(steps.size() == 3 && steps[0].kind == 4 && steps[1].kind == 9 && steps[2].id == ActorId::SysAD, "tie order wrong: %s", dump().c_str());
    timeline.catchUp({50}, ActorId::CPU);
    CHECK(steps.size() == 5 && steps[3].id == ActorId::RDP && steps[4].id == ActorId::RSP, "CPU caller at 50 should run RDP then RSP: %s", dump().c_str());
  }

  //Nesting: an actor that catches up from inside its own step never lets anyone
  //step past its time, the nested call is bounded by the actor count, and the
  //outer call resumes correctly. Defect: stepping an on-stack actor, or a floor
  //that ignores the stack.
  {
    reset();
    Scripted rsp{}; rsp.id = ActorId::RSP; rsp.times = {50, 70}; rsp.nestAt = 50;
    Scripted rdp{}; rdp.id = ActorId::RDP; rdp.times = {40, 60, 80};
    Scripted sysad{}; sysad.id = ActorId::SysAD; sysad.times = {45, 50};
    timeline.attach(ActorId::RSP, &rsp);
    timeline.attach(ActorId::RDP, &rdp);
    timeline.attach(ActorId::SysAD, &sysad);
    timeline.schedule({{50}, 1});
    timeline.schedule({{55}, 2});
    timeline.catchUp({100}, ActorId::CPU);
    //inside the RSP's step at 50: Events(50) and SysAD(50) run (rank below RSP); RDP at 60 and the event at 55 must wait
    CHECK(sorted(), "nested run out of order: %s", dump().c_str());
    u32 rspIndex = 0;
    for(u32 i = 0; i < steps.size(); i++) if(steps[i].id == ActorId::RSP && steps[i].at == 50) rspIndex = i;
    bool before = true;
    for(u32 i = 0; i < steps.size(); i++) {
      if(steps[i].at == 55 || steps[i].at == 60) before = before && i > rspIndex;
    }
    CHECK(before, "a step at 55 or 60 ran before the RSP's step at 50 finished: %s", dump().c_str());
    CHECK(timeline.maxDepth == 2, "nested depth should be 2, got %u", timeline.maxDepth);
    CHECK(steps.size() == 9, "expected 9 steps, got %zu: %s", steps.size(), dump().c_str());
  }

  //The floor is the earliest time on the stack, not the nested caller's target:
  //the RSP's step at 50 reaching for 58 must not run the RDP at 56 past the
  //CPU, which is still at 55. Defect: a floor taken from the target alone.
  {
    reset();
    Scripted rsp{}; rsp.id = ActorId::RSP; rsp.times = {50}; rsp.nestAt = 50; rsp.nestTarget = 58;
    Scripted rdp{}; rdp.id = ActorId::RDP; rdp.times = {56};
    timeline.attach(ActorId::RSP, &rsp);
    timeline.attach(ActorId::RDP, &rdp);
    timeline.catchUp({55}, ActorId::CPU);
    CHECK(rdp.runs == 0, "the RDP at 56 ran past the CPU at 55: %s", dump().c_str());
  }

  //Parked and Blocked actors are never stepped, whatever their time. Defect: the
  //readiness kind ignored.
  {
    reset();
    Scripted parked{}; parked.id = ActorId::RDP; parked.kind = Readiness::Kind::Parked; parked.times = {0};
    Scripted blocked{}; blocked.id = ActorId::SysAD; blocked.kind = Readiness::Kind::Blocked; blocked.times = {0};
    Scripted rsp{}; rsp.id = ActorId::RSP; rsp.times = {10};
    timeline.attach(ActorId::RDP, &parked);
    timeline.attach(ActorId::SysAD, &blocked);
    timeline.attach(ActorId::RSP, &rsp);
    timeline.catchUp({1000}, ActorId::CPU);
    CHECK(parked.runs == 0 && blocked.runs == 0, "a Parked or Blocked actor was stepped");
    CHECK(steps.size() == 1 && steps[0].id == ActorId::RSP, "only the RSP should have stepped: %s", dump().c_str());
    CHECK(timeline.horizon() == Clock::never(), "nothing runnable: horizon should be never, got %lld", (long long)timeline.horizon().units);
  }

  //Batching stays inside the limit: an actor keeps stepping only while its next
  //step starts before every other contender. Defect: run(limit) ignoring limit.
  {
    reset();
    Scripted a{}; a.id = ActorId::RSP; a.times = {10, 12, 14, 16};
    Scripted b{}; b.id = ActorId::RDP; b.times = {13, 16};
    timeline.attach(ActorId::RSP, &a);
    timeline.attach(ActorId::RDP, &b);
    timeline.catchUp({20}, ActorId::CPU);
    CHECK(sorted(), "batched steps crossed another actor's time: %s", dump().c_str());
    CHECK(a.runs == 3 && b.runs == 2, "RSP should run in 3 batches (10,12 | 14 | 16) and RDP in 2, got %u and %u", a.runs, b.runs);
    CHECK(steps.size() == 6 && steps[4].id == ActorId::RDP && steps[4].at == 16 && steps[5].id == ActorId::RSP, "tie at 16 should put RDP before RSP: %s", dump().c_str());
  }

  //Events: out-of-order posting, equal-time order by kind then posting order,
  //cancel reports the latest time, a handler posts relative to its own time, and
  //an event posted during a catch-up fires in that same catch-up. Defect: an
  //unsorted insert, a cancel that keeps a stale entry, now() returning the caller's time.
  {
    reset();
    timeline.schedule({{30}, 5});
    timeline.schedule({{10}, 6});
    timeline.schedule({{10}, 6});
    timeline.schedule({{10}, 3});
    timeline.schedule({{20}, 7});   //reposts kind 8 at 25
    timeline.schedule({{40}, 5});
    CHECK(timeline.cancel(5) == Clock{40}, "cancel should return the latest time of the kind");
    CHECK(timeline.cancel(5) == Clock::never(), "second cancel finds nothing");
    CHECK(!timeline.pending(5) && timeline.pending(6), "pending() wrong after cancel");
    CHECK(timeline.horizon() == Clock{10}, "horizon should be the first event, got %lld", (long long)timeline.horizon().units);
    timeline.catchUp({25}, ActorId::CPU);
    CHECK(steps.size() == 5, "expected 5 events (3 at 10, kind 7 at 20, kind 8 at 25), got %zu: %s", steps.size(), dump().c_str());
    CHECK(steps.size() == 5 && steps[0].kind == 3 && steps[1].kind == 6 && steps[2].kind == 6 && steps[3].kind == 7 && steps[4].kind == 8 && steps[4].at == 25,
      "event order or the reposted time is wrong: %s", dump().c_str());
    CHECK(timeline.now({77}) == Clock{77}, "now() outside a handler returns the fallback");
  }

  //Horizon and wake: the CPU's skip bound is the earliest runnable time, a wake
  //lowers it, and stepCap pins it at zero so every catchUp runs. Defect: a
  //stale cached horizon after another actor is made runnable.
  {
    reset();
    Scripted rsp{}; rsp.id = ActorId::RSP; rsp.kind = Readiness::Kind::Parked; rsp.times = {30, 90};
    timeline.attach(ActorId::RSP, &rsp);
    timeline.schedule({{100}, 1});
    timeline.catchUp({0}, ActorId::CPU);
    CHECK(timeline.horizon() == Clock{100}, "parked RSP must not lower the horizon, got %lld", (long long)timeline.horizon().units);
    rsp.kind = Readiness::Kind::Runnable;   //the CPU unhalts it
    timeline.wake(ActorId::RSP);
    CHECK(timeline.horizon() == Clock{30}, "wake should lower the horizon to 30, got %lld", (long long)timeline.horizon().units);
    timeline.catchUp({29}, ActorId::CPU);
    CHECK(steps.empty(), "catchUp below the horizon must not step: %s", dump().c_str());
    timeline.catchUp({30}, ActorId::CPU);
    CHECK(steps.size() == 1 && steps[0].at == 30, "catchUp at the horizon steps the RSP: %s", dump().c_str());
    CHECK(timeline.horizon() == Clock{90}, "horizon should move to 90, got %lld", (long long)timeline.horizon().units);
    timeline.setStepCap(true);
    CHECK(timeline.horizon() == Clock{0}, "stepCap horizon should be 0, got %lld", (long long)timeline.horizon().units);
    timeline.catchUp({50}, ActorId::CPU);
    CHECK(steps.size() == 1, "stepCap catchUp below the real horizon steps nothing: %s", dump().c_str());
    timeline.catchUp({90}, ActorId::CPU);
    CHECK(steps.size() == 2 && timeline.horizon() == Clock{0}, "stepCap keeps the horizon at 0 after a step");
  }

  //A step that wakes another actor ends the run: the RSP's DPC_END write at 10
  //makes the RDP runnable at 15, so the RSP's step at 20 must wait for it.
  //Defect: a run that keeps stepping to the limit it was given.
  {
    reset();
    Scripted rsp{}; rsp.id = ActorId::RSP; rsp.times = {10, 20, 30};
    Scripted rdp{}; rdp.id = ActorId::RDP; rdp.times = {15}; rdp.kind = Readiness::Kind::Parked;
    rsp.wakeAt = 10; rsp.wakes = &rdp;
    timeline.attach(ActorId::RSP, &rsp);
    timeline.attach(ActorId::RDP, &rdp);
    timeline.catchUp({100}, ActorId::CPU);
    CHECK(sorted() && steps.size() == 4, "a woken actor must run before the waker's later steps: %s", dump().c_str());
  }

  //The same for an event handler: the RDP woken at 15 by the event at 10 runs
  //before the event at 20. Defect: fireEvents keeps the limit it computed
  //before the handler ran (verify-49).
  {
    reset();
    Scripted rdp{}; rdp.id = ActorId::RDP; rdp.times = {15}; rdp.kind = Readiness::Kind::Parked;
    wakeByEvent = &rdp;
    timeline.attach(ActorId::RDP, &rdp);
    timeline.schedule({{10}, 11});
    timeline.schedule({{20}, 12});
    timeline.catchUp({100}, ActorId::CPU);
    CHECK(sorted() && steps.size() == 3, "an actor woken by an event must run before the next event: %s", dump().c_str());
    wakeByEvent = nullptr;
  }

  //The trace does not depend on how events were batched: one catchUp past
  //three events and three catchUps to each of them fold the same records.
  //Defect: one fold per fireEvents batch, which made stepcap compare batch
  //boundaries instead of steps.
  {
    reset();
    for(s64 t : {10, 20, 30}) timeline.schedule({{t}, 1});
    timeline.catchUp({100}, ActorId::CPU);
    const u64 batched = timeline.trace;
    reset();
    for(s64 t : {10, 20, 30}) timeline.schedule({{t}, 1});
    for(s64 t : {10, 20, 30}) timeline.catchUp({t}, ActorId::CPU);
    CHECK(timeline.trace == batched, "trace differs between one batch and one catchUp per event");

    reset();
    Scripted rsp{}; rsp.id = ActorId::RSP; rsp.times = {10, 20, 30};
    timeline.attach(ActorId::RSP, &rsp);
    timeline.catchUp({100}, ActorId::CPU);
    const u64 oneRun = timeline.trace;
    reset();
    Scripted rsp2{}; rsp2.id = ActorId::RSP; rsp2.times = {10, 20, 30};
    timeline.attach(ActorId::RSP, &rsp2);
    for(s64 t : {10, 20, 30}) timeline.catchUp({t}, ActorId::CPU);
    CHECK(timeline.trace == oneRun, "trace differs between one run of three steps and three runs");
  }

  if(failures) std::printf("timeline: %u failure(s)\n", failures);
  else std::printf("timeline: ok\n");
  return failures;
}

auto testRi() -> u32;  //ri.cpp
auto testRiSplit() -> u32;  //ri.cpp

//nall supplies the process entry point and calls this. An argument names one
//test (the checks.tsv selector); none runs all. A nonzero exit reports failures.
auto nall::main(Arguments arguments) -> void {
  const bool all = !arguments;
  u32 failed = 0;
  if(all || arguments.find("timeline")) failed += testTimeline();
  if(all || arguments.find("ri-cost-table")) failed += testRi();
  if(all || arguments.find("ri-split")) failed += testRiSplit();
  if(failed) std::exit(1);
}
