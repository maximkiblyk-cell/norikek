#include "nori/core.hpp"
#include <iostream>
#include <thread>
#include <stdexcept>
using namespace nori; using namespace std::chrono_literals;
struct Shared {std::string value;bool corrupt=false;};
class MemoryVault final:public Vault {std::shared_ptr<Shared> s_; public:explicit MemoryVault(std::shared_ptr<Shared>s):s_(std::move(s)){}void save(const std::string&v)override{s_->value=v;}std::string load()override{if(s_->value.empty()||s_->corrupt)throw std::runtime_error("invalid vault");return s_->value;}void erase()override{s_->value.clear();}bool exists()const override{return !s_->value.empty();}};
void check(bool v,const char*m){if(!v)throw std::runtime_error(m);}void step(){std::string x;std::getline(std::cin,x);check(x=="next","driver");}
AuthView idle(AuthController& a,int ms=10000){auto end=std::chrono::steady_clock::now()+std::chrono::milliseconds(ms);while(std::chrono::steady_clock::now()<end){auto v=a.view();if(!v.busy)return v;std::this_thread::sleep_for(10ms);}throw std::runtime_error("operation timed out");}
void state(AuthController&a,ConnectionState expected){auto v=idle(a);if(v.state!=expected)throw std::runtime_error(std::string("state expected ")+connection_name(expected)+" actual "+connection_name(v.state));}
int main(int argc,char**argv){try{if(argc!=3)return 2;auto shared=std::make_shared<Shared>();Settings settings;auto make=[&](){return std::make_unique<AuthController>(argv[1],settings,std::make_unique<MemoryVault>(shared),argv[2]);};auto a=make();state(*a,ConnectionState::Unpaired);check(a->begin("hassle_rp_2"),"begin");state(*a,ConnectionState::WaitingConfirmation);auto v=a->view();check(!v.code.empty()&&!v.code_expires.empty(),"code and expiry");check(a->complete(),"premature complete");state(*a,ConnectionState::WaitingConfirmation);check(a->view().code==v.code,"code retained");std::cout<<"CODE "<<v.code<<std::endl;step();
 check(a->complete(),"complete");state(*a,ConnectionState::Online);v=a->view();check(v.platform=="hassle_rp_2"&&!v.license_expires.empty()&&!v.device_id.empty(),"license display");check(!shared->value.empty(),"saved");std::cout<<"ONLINE"<<std::endl;step();
 a->shutdown();a=make();state(*a,ConnectionState::Online);std::cout<<"RESTARTED"<<std::endl;step();
 check(a->refresh(),"refresh offline");check(!a->refresh(),"parallel refresh must be rejected");state(*a,ConnectionState::Offline);check(!shared->value.empty(),"offline retains credential");std::cout<<"OFFLINE"<<std::endl;step();
 {auto end=std::chrono::steady_clock::now()+25s;while(std::chrono::steady_clock::now()<end&&a->view().state!=ConnectionState::Online)std::this_thread::sleep_for(20ms);check(a->view().state==ConnectionState::Online,"auto reconnect");}std::cout<<"RECONNECTED"<<std::endl;step();
 check(a->refresh(),"offline for cancel wait");state(*a,ConnectionState::Offline);check(a->view().retry_scheduled,"retry should be scheduled");a->cancel();check(!a->view().retry_scheduled,"retry cancel");std::this_thread::sleep_for(1500ms);check(a->view().state==ConnectionState::Offline&&!a->view().busy&&!a->view().retry_scheduled,"cancelled wait must not reconnect");check(!shared->value.empty(),"wait cancel retains credential");std::cout<<"PAUSED"<<std::endl;step();
 check(a->refresh(),"manual refresh after pause");state(*a,ConnectionState::Online);std::cout<<"AFTER_PAUSE"<<std::endl;step();
 check(a->refresh(),"expiry refresh");state(*a,ConnectionState::Denied);check(!shared->value.empty(),"denied retains credential");std::cout<<"DENIED"<<std::endl;step();
 check(a->refresh(),"renew refresh");state(*a,ConnectionState::Online);std::cout<<"RENEWED"<<std::endl;step();
 check(a->refresh(),"slow refresh");std::this_thread::sleep_for(200ms);a->cancel();state(*a,ConnectionState::Offline);check(!shared->value.empty(),"cancel retains credential");std::cout<<"CANCELLED"<<std::endl;step();
 check(a->refresh(),"shutdown refresh");std::this_thread::sleep_for(200ms);auto start=std::chrono::steady_clock::now();a->shutdown();check(std::chrono::steady_clock::now()-start<7s,"shutdown timeout");check(!shared->value.empty(),"shutdown retains credential");std::cout<<"SHUTDOWN"<<std::endl;step();
 a=make();state(*a,ConnectionState::Online);std::cout<<"RESUMED"<<std::endl;step();
 check(a->refresh(),"revoke refresh");state(*a,ConnectionState::Revoked);check(shared->value.empty(),"revoke erases credential");std::cout<<"REVOKED"<<std::endl;
 a->shutdown();shared->value="corrupted";shared->corrupt=true;a=make();state(*a,ConnectionState::Error);check(!a->view().can_pair&&!shared->value.empty(),"corrupt vault fail closed");std::cout<<"CORRUPT"<<std::endl;return 0;
}catch(const std::exception&e){std::cerr<<"controller test: "<<e.what()<<std::endl;return 1;}}
