//Input scripts: a list of steps the runner executes between VI fields. The script drives
//controller 1 and reads or writes guest memory, so a run can reach a game state from cold
//boot without save files or save states. See tools/n64-timing/README.md for the syntax.

#include <algorithm>
#include <cstdlib>
#include <functional>
#include <variant>
#include <vector>

namespace script {

//A guest address expression: a number, "[expr]" to load the word at expr, and
//"+number" to add an offset, e.g. [[0x801E3FB0]+0x1CCC]+0x24.
struct Expr {
  enum class Op { Push, Load, Add };
  struct Term { Op op; u32 value; };
  std::vector<Term> terms;
};

enum class Width : u32 { Byte = 1, Half = 2, Word = 4 };

struct Wait  { u64 fields; };
enum class Compare { Equal, NotEqual, AtLeast, Below };
struct Until { Expr address; Width width; Compare compare; u32 value; };
struct Input { std::vector<string> buttons; s32 x; s32 y; };
struct Poke  { Expr address; Width width; u32 value; };
struct Copy  { Expr source; Expr target; u32 length; };
struct Peek  { string name; Expr address; Width width; };
struct Mark  { string name; };
struct Shot  { string path; };
struct SaveState { string path; };
struct LoadState { string path; };
struct PokeTmem  { u32 offset; u8 value; };
struct Stop  {};

using Step = std::variant<Wait, Until, Input, Poke, Copy, Peek, Mark, Shot, SaveState, LoadState, PokeTmem, Stop>;

//Controller 1 as the script last set it. Button names are the gamepad's ares node names.
struct Pad {
  std::vector<string> buttons;
  s32 x = 0;
  s32 y = 0;
};

//Decimal, or hex with a 0x prefix. A leading minus is allowed for decimal.
inline auto parseNumber(const string& text) -> maybe<u64> {
  string s = text;
  if(!s) return nothing;
  char* end = nullptr;
  u64 value = s.beginsWith("-") ? (u64)std::strtoll(s.data(), &end, 10) : std::strtoull(s.data(), &end, 0);
  if(end != s.data() + s.size()) return nothing;
  return value;
}

inline auto parseExpr(const string& text) -> maybe<Expr> {
  Expr expr;
  string s = text;
  u32 pos = 0;
  std::function<bool ()> term = [&]() -> bool {
    if(pos < s.size() && s[pos] == '[') {
      pos++;
      if(!term()) return false;
      while(pos < s.size() && s[pos] == '+') {
        pos++;
        u32 start = pos;
        while(pos < s.size() && s[pos] != '+' && s[pos] != ']') pos++;
        auto offset = parseNumber(slice(s, start, pos - start));
        if(!offset) return false;
        expr.terms.push_back({Expr::Op::Add, (u32)*offset});
      }
      if(pos >= s.size() || s[pos] != ']') return false;
      pos++;
      expr.terms.push_back({Expr::Op::Load, 0});
      return true;
    }
    u32 start = pos;
    while(pos < s.size() && s[pos] != '+' && s[pos] != ']') pos++;
    auto value = parseNumber(slice(s, start, pos - start));
    if(!value) return false;
    expr.terms.push_back({Expr::Op::Push, (u32)*value});
    return true;
  };
  if(!term()) return nothing;
  while(pos < s.size() && s[pos] == '+') {
    pos++;
    u32 start = pos;
    while(pos < s.size() && s[pos] != '+') pos++;
    auto offset = parseNumber(slice(s, start, pos - start));
    if(!offset) return nothing;
    expr.terms.push_back({Expr::Op::Add, (u32)*offset});
  }
  if(pos != s.size()) return nothing;
  return expr;
}

inline auto parseWidth(const string& text) -> maybe<Width> {
  string s = text;
  if(s == "b") return Width::Byte;
  if(s == "h") return Width::Half;
  if(s == "w") return Width::Word;
  return nothing;
}

inline const std::vector<string> ButtonNames = {
  "A", "B", "Z", "Start", "L", "R", "Up", "Down", "Left", "Right",
  "C-Up", "C-Down", "C-Left", "C-Right",
};

//Returns the steps, or the 1-based number of the first line that does not parse.
inline auto parse(const string& text) -> std::variant<std::vector<Step>, u32> {
  std::vector<Step> steps;
  u32 lineNumber = 0;
  for(auto line : nall::split(text, "\n")) {
    lineNumber++;
    if(auto comment = line.find("#")) line = slice(line, 0, *comment);
    line.strip();
    if(!line) continue;
    std::vector<string> words;
    for(auto& word : nall::split(line, " ")) if(word) words.push_back(word);
    auto& verb = words[0];
    auto fail = [&] { return std::variant<std::vector<Step>, u32>{lineNumber}; };

    if(verb == "wait" && words.size() == 2) {
      auto n = parseNumber(words[1]);
      if(!n) return fail();
      steps.push_back(Wait{*n});
    } else if(verb == "until" && words.size() == 5) {
      auto address = parseExpr(words[1]);
      auto width = parseWidth(words[2]);
      auto value = parseNumber(words[4]);
      maybe<Compare> compare;
      if(words[3] == "==") compare = Compare::Equal;
      if(words[3] == "!=") compare = Compare::NotEqual;
      if(words[3] == ">=") compare = Compare::AtLeast;
      if(words[3] == "<")  compare = Compare::Below;
      if(!address || !width || !value || !compare) return fail();
      steps.push_back(Until{*address, *width, *compare, (u32)*value});
    } else if(verb == "input") {
      Input input{{}, 0, 0};
      for(u32 i = 1; i < words.size(); i++) {
        auto& word = words[i];
        if(word.beginsWith("x=") || word.beginsWith("y=")) {
          auto number = parseNumber(slice(word, 2));
          if(!number) return fail();
          (word[0] == 'x' ? input.x : input.y) = (s32)(s64)*number;
        } else if(std::find(ButtonNames.begin(), ButtonNames.end(), word) != ButtonNames.end()) {
          input.buttons.push_back(word);
        } else {
          return fail();
        }
      }
      steps.push_back(input);
    } else if(verb == "poke" && words.size() == 4) {
      auto address = parseExpr(words[1]);
      auto width = parseWidth(words[2]);
      auto value = parseNumber(words[3]);
      if(!address || !width || !value) return fail();
      steps.push_back(Poke{*address, *width, (u32)*value});
    } else if(verb == "copy" && words.size() == 4) {
      auto source = parseExpr(words[1]);
      auto target = parseExpr(words[2]);
      auto length = parseNumber(words[3]);
      if(!source || !target || !length) return fail();
      steps.push_back(Copy{*source, *target, (u32)*length});
    } else if(verb == "peek" && words.size() == 4) {
      auto address = parseExpr(words[2]);
      auto width = parseWidth(words[3]);
      if(!address || !width) return fail();
      steps.push_back(Peek{words[1], *address, *width});
    } else if(verb == "mark" && words.size() == 2) {
      steps.push_back(Mark{words[1]});
    } else if(verb == "shot" && words.size() == 2) {
      steps.push_back(Shot{words[1]});
    } else if(verb == "save-state" && words.size() == 2) {
      steps.push_back(SaveState{words[1]});
    } else if(verb == "load-state" && words.size() == 2) {
      steps.push_back(LoadState{words[1]});
    } else if(verb == "poke-tmem" && words.size() == 3) {
      auto offset = parseNumber(words[1]);
      auto value = parseNumber(words[2]);
      if(!offset || *offset >= 0x1000 || !value) return fail();
      steps.push_back(PokeTmem{(u32)*offset, (u8)*value});
    } else if(verb == "stop" && words.size() == 1) {
      steps.push_back(Stop{});
    } else {
      return fail();
    }
  }
  return steps;
}

}
