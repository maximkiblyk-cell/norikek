#include "nori/core.hpp"
namespace nori {bool Input::key(bool down,const std::string& key,const std::string& configured){if(key!=configured)return false; if(!down){held_=false;return false;}if(held_)return false;held_=true;open_=!open_;return true;}}
