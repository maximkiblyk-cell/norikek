#include "nori/core.hpp"
#include <iostream>
#include <stdexcept>
using namespace nori;
int main(){try{RetryBackoff low,high;const long caps[]={1000,2000,4000,8000,16000,32000,60000,60000,60000};for(auto cap:caps){auto a=low.next(0).count();auto b=high.next(static_cast<std::uint32_t>(cap-cap/2)).count();if(a!=cap/2||b!=cap)throw std::runtime_error("jitter range, exponential sequence or cap");}low.reset();if(low.next(0).count()!=500)throw std::runtime_error("reset");RetryBackoff variable1,variable2;if(variable1.next(1)==variable2.next(2))throw std::runtime_error("sample has no effect");bool rejected=false;try{AuthController a("https://localhost",Settings{},nullptr);}catch(const std::invalid_argument&){rejected=true;}if(!rejected)throw std::runtime_error("null vault not rejected");std::cout<<"PASS null vault rejection; exponential equal jitter 0.5-1x, cap 60s, saturation, reset\n";return 0;}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
