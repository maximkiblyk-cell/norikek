#include "nori/core.hpp"
#include <openssl/rand.h>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#ifdef _WIN32
#include <windows.h>
#endif
namespace nori {
std::string new_device_id(){unsigned char b[16];if(RAND_bytes(b,sizeof b)!=1)throw std::runtime_error("secure random unavailable");b[6]=(b[6]&15)|0x40;b[8]=(b[8]&63)|0x80;std::ostringstream s;for(int i=0;i<16;i++){if(i==4||i==6||i==8||i==10)s<<'-';s<<std::hex<<std::setw(2)<<std::setfill('0')<<int(b[i]);}return s.str();}
static void validate(const Settings& s){if(s.version!=1||s.device_id.size()!=36||s.ui_scale<75||s.ui_scale>150||s.ui_scale%25!=0||(s.hotkey!="Insert"&&s.hotkey!="F8"&&s.hotkey!="F9"&&s.hotkey!="F10"))throw std::runtime_error("invalid settings");}
Settings SettingsStore::load()const{if(!std::filesystem::exists(path_)){Settings s;s.device_id=new_device_id();save(s);return s;}std::ifstream f(path_,std::ios::binary);if(!f)throw std::runtime_error("settings read failed");if(std::filesystem::file_size(path_)>16384)throw std::runtime_error("settings too large");json j;try{f>>j;Settings s;s.version=j.at("version").get<int>();s.device_id=j.at("device_id").get<std::string>();s.hotkey=j.at("hotkey").get<std::string>();s.ui_scale=j.at("ui_scale").get<int>();s.notifications=j.at("notifications").get<bool>();s.reduced_motion=j.at("reduced_motion").get<bool>();validate(s);return s;}catch(const std::exception&){throw std::runtime_error("settings invalid; file retained");}}
void SettingsStore::save(const Settings&s)const{validate(s);auto parent=path_.parent_path();if(!parent.empty())std::filesystem::create_directories(parent);json j={{"version",s.version},{"device_id",s.device_id},{"hotkey",s.hotkey},{"ui_scale",s.ui_scale},{"notifications",s.notifications},{"reduced_motion",s.reduced_motion}};auto tmp=path_;tmp+=".tmp";{std::ofstream f(tmp,std::ios::binary|std::ios::trunc);if(!f)throw std::runtime_error("settings write failed");f<<j.dump(2)<<'\n';f.flush();if(!f)throw std::runtime_error("settings write failed");}
#ifdef _WIN32
 if(!MoveFileExW(tmp.c_str(),path_.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH)){std::filesystem::remove(tmp);throw std::runtime_error("settings replace failed");}
#else
 std::filesystem::rename(tmp,path_);
#endif
}
Settings SettingsStore::reset()const{Settings old=load();Settings s;s.device_id=old.device_id;save(s);return s;}
}
