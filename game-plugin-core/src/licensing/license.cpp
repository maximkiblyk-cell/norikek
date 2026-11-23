#include "nori/core.hpp"
#include <regex>
#include <optional>
namespace nori {namespace {
std::optional<long long> parse_utc(const std::string& s){static const std::regex r(R"(^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?(Z|[+-]\d{2}:\d{2})$)");std::smatch m;if(!std::regex_match(s,m,r))return {};int y=std::stoi(m[1]),mon=std::stoi(m[2]),d=std::stoi(m[3]),h=std::stoi(m[4]),mi=std::stoi(m[5]),sec=std::stoi(m[6]);std::chrono::year_month_day date{std::chrono::year{y},std::chrono::month{unsigned(mon)},std::chrono::day{unsigned(d)}};if(!date.ok()||h>23||mi>59||sec>59)return {};long long result=std::chrono::sys_days(date).time_since_epoch().count()*86400LL+h*3600+mi*60+sec;std::string z=m[7];if(z!="Z"){int zh=std::stoi(z.substr(1,2)),zm=std::stoi(z.substr(4,2));if(zh>23||zm>59)return {};long long delta=zh*3600+zm*60;result+=z[0]=='+'?-delta:delta;}return result;}
}
bool LicenseGate::apply_v2(const HttpResponse&r){offline();if(!r.error.empty()||r.status!=200)return false;try{auto j=json::parse(r.body);if(j.at("status")!="active"||!j.at("license_id").is_number_integer()||j.at("license_id").get<long long>()<=0||!j.at("device_id").is_string())return false;auto p=j.at("platform").get<std::string>();if(p!="hassle_rp_2"&&p!="radmir_crmp")return false;auto server=parse_utc(j.at("server_time").get<std::string>()),expiry=parse_utc(j.at("expires_at").get<std::string>());if(!server||!expiry||*expiry<=*server)return false;auto seconds=std::min<long long>(*expiry-*server,86400LL*3650);deadline_=std::chrono::steady_clock::now()+std::chrono::seconds(seconds);online_=verified_=true;return true;}catch(...){return false;}}
// No command authorization until server v2 supports a fresh per-action check.
bool LicenseGate::permits()const{return false;}
}
