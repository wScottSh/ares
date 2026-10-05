auto RDP::Debugger::load(Node::Object parent) -> void {
  tracer.command = parent->append<Node::Debugger::Tracer::Notification>("Command", "RDP");
  tracer.io = parent->append<Node::Debugger::Tracer::Notification>("I/O", "RDP");
}

//Names each command as the command processor dispatches it.
auto RDP::Debugger::command(u64 word) -> void {
  if(likely(!tracer.command->enabled())) return;

  static const string names[64] = {
    "No_Operation", "Invalid_01", "Invalid_02", "Invalid_03",
    "Invalid_04", "Invalid_05", "Invalid_06", "Invalid_07",
    "Unshaded_Triangle", "Unshaded_Zbuffer_Triangle",
    "Texture_Triangle", "Texture_Zbuffer_Triangle",
    "Shaded_Triangle", "Shaded_Zbuffer_Triangle",
    "Shaded_Texture_Triangle", "Shaded_Texture_Zbuffer_Triangle",
    "Invalid_10", "Invalid_11", "Invalid_12", "Invalid_13",
    "Invalid_14", "Invalid_15", "Invalid_16", "Invalid_17",
    "Invalid_18", "Invalid_19", "Invalid_1a", "Invalid_1b",
    "Invalid_1c", "Invalid_1d", "Invalid_1e", "Invalid_1f",
    "Invalid_20", "Invalid_21", "Invalid_22", "Invalid_23",
    "Texture_Rectangle", "Texture_Rectangle_Flip",
    "Sync_Load", "Sync_Pipe", "Sync_Tile", "Sync_Full",
    "Set_Key_GB", "Set_Key_R", "Set_Convert", "Set_Scissor",
    "Set_Primitive_Depth", "Set_Other_Modes", "Load_Texture_LUT", "Invalid_31",
    "Set_Tile_Size", "Load_Block", "Load_Tile", "Set_Tile",
    "Fill_Rectangle", "Set_Fill_Color", "Set_Fog_Color", "Set_Blend_Color",
    "Set_Primitive_Color", "Set_Environment_Color", "Set_Combine_Mode", "Set_Texture_Image",
    "Set_Mask_Image", "Set_Color_Image",
  };
  tracer.command->notify(string{hex(word, 16L), "  ", names[word >> 56 & 0x3f]});
}

auto RDP::Debugger::ioDPC(bool mode, u32 address, u32 data) -> void {
  static const std::vector<string> registerNames = {
    "DPC_START",
    "DPC_END",
    "DPC_CURRENT",
    "DPC_STATUS",
    "DPC_CLOCK",
    "DPC_BUSY",
    "DPC_PIPE_BUSY",
    "DPC_TMEM_BUSY",
  };

  if(unlikely(tracer.io->enabled())) {
    string message;
    string name = (address < registerNames.size() ? registerNames[address] : string("DPC_UNKNOWN"));
    if(mode == Read) {
      message = {nall::split(name, "|").front(), " => ", hex(data, 8L)};
    }
    if(mode == Write) {
      message = {nall::split(name, "|").back(), " <= ", hex(data, 8L)};
    }
    tracer.io->notify(message);
  }
}

auto RDP::Debugger::ioDPS(bool mode, u32 address, u32 data) -> void {
  static const std::vector<string> registerNames = {
    "DPS_TBIST",
    "DPS_TEST_MODE",
    "DPS_BUFTEST_ADDR",
    "DPS_BUFTEST_DATA",
  };

  if(unlikely(tracer.io->enabled())) {
    string message;
    string name = (address < registerNames.size() ? registerNames[address] : string("DPS_UNKNOWN"));
    if(mode == Read) {
      message = {nall::split(name, "|").front(), " => ", hex(data, 8L)};
    }
    if(mode == Write) {
      message = {nall::split(name, "|").back(), " <= ", hex(data, 8L)};
    }
    tracer.io->notify(message);
  }
}
