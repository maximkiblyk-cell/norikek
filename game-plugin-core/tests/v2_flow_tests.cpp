#include "nori/core.hpp"
#include <iostream>
#include <stdexcept>
using namespace nori;
// Test-only vault. It is never built into the core or developer host and does not
// represent persistent/Windows secure storage.
class TestMemoryVault final:public Vault {std::string value_;public:void save(const std::string&s)override{value_=s;}std::string load()override{if(value_.empty())throw std::runtime_error("empty");return value_;}void erase()override{value_.clear();}bool empty()const{return value_.empty();}};
void check(bool b,const char*m){if(!b)throw std::runtime_error(m);}
void wait(){std::string s;std::getline(std::cin,s);if(s!="next")throw std::runtime_error("invalid test driver");}
int main(int argc,char**argv){try{
 if(argc!=3)return 2;HttpClient http;TestMemoryVault vault;LicenseGate gate;ClientSession session(argv[1],http,vault,gate,argv[2]);Settings s;std::atomic_bool cancel=false;
 auto code=session.begin(s,"hassle_rp_2","Core integration test",cancel);
 check(!session.complete(cancel)&&session.state()==ConnectionState::WaitingConfirmation,"pre-confirm must wait");
 std::cout<<"CODE "<<code<<std::endl;wait();
 check(session.complete(cancel)&&session.state()==ConnectionState::Online&&gate.online()&&!gate.permits(),"confirmed claim or access");std::cout<<"ONLINE"<<std::endl;wait();
 check(!session.refresh(cancel)&&session.state()==ConnectionState::Offline&&!gate.online()&&!gate.permits(),"unavailable must fail closed");std::cout<<"OFFLINE"<<std::endl;wait();
 check(session.refresh(cancel)&&gate.online(),"reconnect must refresh");std::cout<<"RECONNECTED"<<std::endl;wait();
 check(!session.refresh(cancel)&&session.state()==ConnectionState::Denied&&!gate.online(),"expired must deny");std::cout<<"DENIED"<<std::endl;wait();
 check(session.refresh(cancel)&&gate.online(),"renewed");std::cout<<"RENEWED"<<std::endl;wait();
 check(!session.refresh(cancel)&&session.state()==ConnectionState::Revoked&&vault.empty()&&!gate.permits(),"revoke");std::cout<<"REVOKED"<<std::endl;return 0;
}catch(const std::exception&e){std::cerr<<"test error: "<<e.what()<<'\n';return 1;}}
