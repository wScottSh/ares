// RI-arbiter-shaped microbenchmark (measure-9), shaped on ADR 0001 Decision 2.
// Twelve requesters post bursts into per-requester FIFOs. The bus is one actor in a
// timeline: each step picks the actor with the smallest time (linear scan, as catchUp
// would). A bus decision picks argmin(rank, arrival, requester) over arrived FIFO heads,
// charges wire time from 8-bank open-row/dirty state, copies the bytes between an 8 MiB
// RDRAM array and the client's buffer, and calls the client's granted() through a
// function pointer. The client then thinks and posts its next burst.
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

using Clock = int64_t;

struct Burst { uint32_t address; uint8_t bytes; bool write; Clock arrival; uint64_t sequence; };

struct Requester;
using Granted = void (*)(Requester&, Clock complete);

struct Requester {
  int id, rank;
  uint32_t weight;          // relative burst share, from the MM counts
  uint8_t bytes; bool write;
  uint32_t think;           // units between a grant and the next post
  uint32_t base, span;      // address window
  Burst ring[16]; uint32_t head = 0, tail = 0;
  alignas(64) uint8_t buffer[128];
  uint32_t rng;
  uint64_t grants = 0; Clock waited = 0;
  Granted granted;
  bool empty() const { return head == tail; }
};

static std::vector<uint8_t> rdram(8u << 20);
static Clock busFree = 0;
static uint64_t sequence = 0, grantCount = 0;
struct Bank { uint32_t row = ~0u; bool dirty = false; } banks[8];

static void post(Requester& r, Clock at) {
  r.rng = r.rng * 1664525u + 1013904223u;
  uint32_t address = (r.base + (r.rng >> 8) % r.span) & ~127u;
  r.ring[r.tail++ & 15] = {address, r.bytes, r.write, at, sequence++};
}

static void grantedPostNext(Requester& r, Clock complete) {
  post(r, complete + r.think + (r.rng >> 27));
}

static std::vector<Requester> makeRequesters(double contention) {
  // id, rank, weight (bursts per 600 MM fields, thousands), bytes, write, think units
  struct Row { int rank; uint32_t weight; uint8_t bytes; bool write; uint32_t think; };
  Row rows[] = {
    {0,   165, 128, false, 0},   // refresh (modelled as a burst)
    {1,   720, 128, false, 0},   // VI fetch
    {2,  2527,  16, false, 0},   // CPU D-fill
    {2,  1620,  16, true,  0},   // CPU D-writeback
    {2,  1521,  32, false, 0},   // CPU I-fill
    {2,   356, 128, false, 0},   // SP DMA
    {2,  2000,  64, false, 0},   // DP color read
    {2,  2000,  64, true,  0},   // DP color write
    {2,  2000,  64, false, 0},   // DP depth read
    {2,  2000,  64, true,  0},   // DP depth write
    {2,   286,   8, false, 0},   // AI
    {2,    23, 128, true,  0},   // PI
  };
  uint64_t total = 0; for(auto& r : rows) total += r.weight;
  std::vector<Requester> rs(12);
  for(int i = 0; i < 12; i++) {
    auto& r = rs[i];
    r.id = i; r.rank = rows[i].rank; r.weight = rows[i].weight;
    r.bytes = rows[i].bytes; r.write = rows[i].write;
    // think time so each requester's share of bursts tracks its MM weight; contention
    // scales all think times down (higher contention = more requesters queued at once)
    r.think = (uint32_t)(60.0 * total / r.weight / contention);
    r.base = (uint32_t)(i * (640u << 10)); r.span = 512u << 10;
    r.rng = 0x9e3779b9u * (i + 1);
    r.granted = grantedPostNext;
    post(r, i);
  }
  return rs;
}

static Clock decide(std::vector<Requester>& rs, Clock now, uint64_t& checksum) {
  int best = -1;
  for(int i = 0; i < (int)rs.size(); i++) {
    auto& r = rs[i];
    if(r.empty()) continue;
    auto& b = r.ring[r.head & 15];
    if(b.arrival > now) continue;
    if(best < 0) { best = i; continue; }
    auto& c = rs[best].ring[rs[best].head & 15];
    if(r.rank < rs[best].rank || (r.rank == rs[best].rank && b.arrival < c.arrival)) best = i;
  }
  if(best < 0) {
    Clock next = INT64_MAX;
    for(auto& r : rs) if(!r.empty() && r.ring[r.head & 15].arrival < next) next = r.ring[r.head & 15].arrival;
    return next;
  }
  auto& r = rs[best];
  auto b = r.ring[r.head++ & 15];
  auto& bank = banks[(b.address >> 20) & 7];
  uint32_t row = b.address >> 11;
  Clock wire = 4 * ((b.bytes + 7) / 8) + 7;
  if(bank.row != row) wire += bank.dirty ? 30 : 22;
  bank.row = row; bank.dirty = b.write;
  if(b.write) memcpy(&rdram[b.address], r.buffer, b.bytes);
  else memcpy(r.buffer, &rdram[b.address], b.bytes);
  r.waited += now - b.arrival; r.grants++;
  busFree = now + wire; grantCount++;
  checksum += r.buffer[b.bytes - 1];
  r.granted(r, busFree);
  return busFree;
}

// The timeline: five non-bus actors plus the bus; each step scans for the minimum.
static double run(double contention, uint64_t decisions, uint64_t& checksum, double& waitPerGrant) {
  auto rs = makeRequesters(contention);
  busFree = 0; for(auto& b : banks) b = {};
  Clock actors[6] = {INT64_MAX - 5, INT64_MAX - 4, INT64_MAX - 3, INT64_MAX - 2, INT64_MAX - 1, 0};
  volatile int sink = 0;
  auto t0 = std::chrono::steady_clock::now();
  grantCount = 0;
  while(grantCount < decisions) {
    int m = 0;
    for(int i = 1; i < 6; i++) if(actors[i] < actors[m]) m = i;
    sink = m;
    Clock next = decide(rs, actors[5], checksum);
    actors[5] = next > actors[5] ? next : actors[5] + 1;
  }
  double s = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
  uint64_t grants = 0; Clock waited = 0;
  for(auto& r : rs) { grants += r.grants; waited += r.waited; checksum += r.grants; }
  waitPerGrant = (double)waited / grants;
  return s;
}

int main(int argc, char** argv) {
  uint64_t decisions = argc > 1 ? strtoull(argv[1], 0, 10) : 50000000ull;
  uint64_t sum = 0;
  for(int rep = 0; rep < 5; rep++) {
    for(double contention : {0.25, 1.0, 4.0}) {
      double wait;
      double s = run(contention, decisions, sum, wait);
      printf("rep=%d contention=%.2f decisions=%llu ns_per_decision=%.2f avg_wait_units=%.1f\n",
        rep, contention, (unsigned long long)decisions, s * 1e9 / decisions, wait);
    }
  }
  printf("checksum=%llu\n", (unsigned long long)sum);
}
