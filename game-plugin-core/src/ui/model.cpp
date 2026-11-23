#include "nori/core.hpp"
namespace nori {const char* state_name(ViewState s){switch(s){case ViewState::Loading:return "Loading";case ViewState::Empty:return "Empty";case ViewState::Success:return "Success";case ViewState::Error:return "Error";case ViewState::Offline:return "Offline";case ViewState::Disabled:return "Disabled";case ViewState::NotConnected:return "Not Connected";}return "Error";}}
