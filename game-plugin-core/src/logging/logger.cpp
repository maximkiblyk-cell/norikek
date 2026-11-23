#include "nori/core.hpp"
#include <fstream>
namespace nori {void Logger::event(LogCode code){std::lock_guard lock(mutex_);std::ofstream f(path_,std::ios::app);if(!f)return;static const char* names[]={"STARTED","STOPPED","SETTINGS_SAVED","NETWORK_ERROR","UNAUTHORIZED","STORAGE_ERROR"};int i=static_cast<int>(code);if(i>=0&&i<6)f<<names[i]<<'\n';}}
