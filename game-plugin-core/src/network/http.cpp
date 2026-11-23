#include "nori/core.hpp"
#include <curl/curl.h>
#include <thread>
#include <stdexcept>
#include <algorithm>
#include <mutex>
namespace nori {namespace {
size_t write_data(char*p,size_t s,size_t n,void*v){auto& out=*static_cast<std::string*>(v);if(s && n>262144/s)return 0;auto count=s*n;if(out.size()+count>262144)return 0;out.append(p,count);return count;}
int progress(void*p,curl_off_t,curl_off_t,curl_off_t,curl_off_t){return static_cast<const std::atomic_bool*>(p)->load()?1:0;}
bool safe_header(const std::string&s){return s.find_first_of("\r\n")==std::string::npos;}
}
bool RequestHandle::ready(){return future_.wait_for(std::chrono::milliseconds(0))==std::future_status::ready;}
HttpResponse HttpClient::perform(const HttpRequest&r,const std::atomic_bool& cancel)const{
 static std::once_flag flag;std::call_once(flag,[]{if(curl_global_init(CURL_GLOBAL_DEFAULT)!=CURLE_OK)throw std::runtime_error("curl initialization failed");});
 if(r.url.rfind("https://",0)!=0||!safe_header(r.bearer)||r.connect_timeout_ms<1||r.timeout_ms<1||(r.method!="GET"&&r.method!="POST"))return {0,"","invalid request",false};
 unsigned tries=r.method=="GET"?std::min(r.retries,2u)+1:1;
 for(unsigned attempt=0;attempt<tries;attempt++){
  if(cancel.load())return {0,"","cancelled",true};CURL*c=curl_easy_init();if(!c)return {0,"","network initialization failed",false};HttpResponse out;curl_slist* headers=nullptr;headers=curl_slist_append(headers,"Accept: application/json");if(r.method=="POST")headers=curl_slist_append(headers,"Content-Type: application/json");std::string auth;if(!r.bearer.empty()){auth="Authorization: Bearer "+r.bearer;headers=curl_slist_append(headers,auth.c_str());}
  bool options_ok=true;
#define NORI_CURL_SET(option,value) do { if(curl_easy_setopt(c,option,value)!=CURLE_OK)options_ok=false; } while(false)
  NORI_CURL_SET(CURLOPT_URL,r.url.c_str());NORI_CURL_SET(CURLOPT_PROTOCOLS_STR,"https");NORI_CURL_SET(CURLOPT_FOLLOWLOCATION,0L);NORI_CURL_SET(CURLOPT_SSL_VERIFYPEER,1L);NORI_CURL_SET(CURLOPT_SSL_VERIFYHOST,2L);NORI_CURL_SET(CURLOPT_SSLVERSION,CURL_SSLVERSION_TLSv1_2);NORI_CURL_SET(CURLOPT_CONNECTTIMEOUT_MS,r.connect_timeout_ms);NORI_CURL_SET(CURLOPT_TIMEOUT_MS,r.timeout_ms);NORI_CURL_SET(CURLOPT_NOSIGNAL,1L);NORI_CURL_SET(CURLOPT_NOPROGRESS,0L);NORI_CURL_SET(CURLOPT_XFERINFOFUNCTION,progress);NORI_CURL_SET(CURLOPT_XFERINFODATA,&cancel);NORI_CURL_SET(CURLOPT_WRITEFUNCTION,write_data);NORI_CURL_SET(CURLOPT_WRITEDATA,&out.body);NORI_CURL_SET(CURLOPT_HTTPHEADER,headers);NORI_CURL_SET(CURLOPT_PROXY,"");
  if(!r.ca_file.empty())NORI_CURL_SET(CURLOPT_CAINFO,r.ca_file.c_str());
  if(r.method=="POST"){NORI_CURL_SET(CURLOPT_POST,1L);NORI_CURL_SET(CURLOPT_POSTFIELDS,r.body.data());NORI_CURL_SET(CURLOPT_POSTFIELDSIZE_LARGE,static_cast<curl_off_t>(r.body.size()));}
#undef NORI_CURL_SET
  if(!options_ok){curl_slist_free_all(headers);curl_easy_cleanup(c);std::fill(auth.begin(),auth.end(),'\0');return {0,"","network security configuration unavailable",false};}
  CURLcode code=curl_easy_perform(c);curl_easy_getinfo(c,CURLINFO_RESPONSE_CODE,&out.status);curl_slist_free_all(headers);curl_easy_cleanup(c);std::fill(auth.begin(),auth.end(),'\0');
  if(cancel.load()){out.body.clear();out.error="cancelled";out.cancelled=true;return out;}
  if(code!=CURLE_OK){out.body.clear();out.error=(code==CURLE_PEER_FAILED_VERIFICATION||code==CURLE_SSL_CONNECT_ERROR||code==CURLE_SSL_CACERT_BADFILE)?"TLS verification or connection failed":(code==CURLE_OPERATION_TIMEDOUT?"timeout":("network error "+std::to_string(static_cast<int>(code))));}
  bool retryable=(code==CURLE_COULDNT_CONNECT||code==CURLE_COULDNT_RESOLVE_HOST||code==CURLE_OPERATION_TIMEDOUT||out.status==502||out.status==503||out.status==504);
  if(!retryable||attempt+1==tries)return out;for(int i=0;i<10*(1<<attempt);++i){if(cancel.load())return {0,"","cancelled",true};std::this_thread::sleep_for(std::chrono::milliseconds(10));}
 }return {0,"","network error",false};}
RequestHandle HttpClient::async(HttpRequest r)const{auto stop=std::make_shared<std::atomic_bool>(false);return RequestHandle(stop,std::async(std::launch::async,[r=std::move(r),stop]()mutable{HttpClient client;auto response=client.perform(r,*stop);std::fill(r.bearer.begin(),r.bearer.end(),'\0');std::fill(r.body.begin(),r.body.end(),'\0');return response;}));}
}
