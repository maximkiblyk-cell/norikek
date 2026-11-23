#include "nori/core.hpp"
#include <algorithm>
#include <stdexcept>
namespace nori {
namespace { void clear(std::string& s){std::fill(s.begin(),s.end(),'\0');s.clear();} }
void ClientSession::cancel_pairing(){if(pairing_){clear(pairing_->claim_secret);clear(pairing_->code);}pairing_.reset();gate_.offline();state_=ConnectionState::Unpaired;}
ClientSession::~ClientSession(){if(pairing_){clear(pairing_->claim_secret);clear(pairing_->code);}gate_.offline();}
std::string ClientSession::begin(const Settings& s,const std::string& platform,const std::string& name,const std::atomic_bool& cancel){
 gate_.offline(); if(pairing_){clear(pairing_->claim_secret);clear(pairing_->code);}pairing_.reset();state_=ConnectionState::Unpaired;
 try{pairing_=api_.start(s,platform,name,cancel);state_=ConnectionState::WaitingConfirmation;return pairing_->code;}
 catch(...){state_=ConnectionState::Error;throw;}
}
bool ClientSession::complete(const std::atomic_bool& cancel){
 gate_.offline();if(!pairing_ || state_!=ConnectionState::WaitingConfirmation)throw std::runtime_error("no pending pairing");
 try{api_.claim(*pairing_,vault_,cancel);clear(pairing_->code);pairing_.reset();return refresh(cancel);}
 catch(const std::exception& e){if(std::string(e.what())=="pairing not confirmed")return false;clear(pairing_->claim_secret);clear(pairing_->code);pairing_.reset();state_=ConnectionState::Error;throw;}
}
bool ClientSession::refresh(const std::atomic_bool& cancel){
 gate_.offline();info_={};std::string credential;
 try{credential=vault_.load();auto r=api_.access(credential,cancel);clear(credential);
  if(!r.error.empty()||r.status==0||r.status>=500||r.status==429){state_=ConnectionState::Offline;return false;}
  if(r.status==401){vault_.erase();state_=ConnectionState::Revoked;return false;}
  if(r.status==403){state_=ConnectionState::Denied;return false;}
  if(!gate_.apply_v2(r)){state_=ConnectionState::Error;return false;}
  try{auto j=json::parse(r.body);info_={j.at("platform").get<std::string>(),j.at("expires_at").get<std::string>(),j.at("device_id").get<std::string>()};}catch(...){gate_.offline();state_=ConnectionState::Error;return false;}
  state_=ConnectionState::Online;return true;
 }catch(...){clear(credential);gate_.offline();state_=ConnectionState::Error;return false;}
}
}
