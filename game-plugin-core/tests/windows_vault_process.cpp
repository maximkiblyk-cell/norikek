#include "nori/core.hpp"
#include <fstream>
#include <iostream>
#include <stdexcept>
using namespace nori;
int main(int argc,char**argv){try{if(argc!=3)return 2;std::string mode=argv[1];std::filesystem::path path=argv[2];auto vault=make_vault(path);const std::string test="nori-dpapi-test-secret-not-a-credential";
 if(mode=="write"){vault->save(test);std::ifstream f(path,std::ios::binary);std::string bytes((std::istreambuf_iterator<char>(f)),{});if(bytes.empty()||bytes.find(test)!=std::string::npos)throw std::runtime_error("plaintext detected");}
 else if(mode=="read"){if(vault->load()!=test)throw std::runtime_error("cross-process read failed");}
 else if(mode=="probe"){vault->save(test);if(vault->load()!=test)throw std::runtime_error("second profile vault unavailable");vault->erase();}
 else if(mode=="reject"){std::ifstream f(path,std::ios::binary);if(!f||f.peek()==std::ifstream::traits_type::eof())throw std::runtime_error("foreign ciphertext not readable");f.close();bool rejected=false;try{(void)vault->load();}catch(...){rejected=true;}if(!rejected)throw std::runtime_error("foreign profile decrypted credential");}
 else if(mode=="corrupt"){std::ofstream f(path,std::ios::binary|std::ios::trunc);f<<"corrupt";f.close();bool failed=false;try{vault->load();}catch(...){failed=true;}if(!failed)throw std::runtime_error("corrupt vault accepted");vault->erase();}
 else return 2;return 0;}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
