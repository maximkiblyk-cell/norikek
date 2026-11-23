#include "nori/core.hpp"
#include <fstream>
#include <stdexcept>
#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#include <wincrypt.h>
#endif
namespace nori {namespace {
#ifdef _WIN32
struct BlobOwner { DATA_BLOB value{}; ~BlobOwner(){if(value.pbData){SecureZeroMemory(value.pbData,value.cbData);LocalFree(value.pbData);}} };
class DPAPIVault final:public Vault {
 std::filesystem::path path_;
public:
 explicit DPAPIVault(std::filesystem::path p):path_(std::move(p)){}
 void save(const std::string& secret) override {
  if(secret.empty()||secret.size()>1024)throw std::runtime_error("invalid secret");
  DATA_BLOB input{static_cast<DWORD>(secret.size()),reinterpret_cast<BYTE*>(const_cast<char*>(secret.data()))};BlobOwner out;
  if(!CryptProtectData(&input,L"NORI Device",nullptr,nullptr,nullptr,CRYPTPROTECT_UI_FORBIDDEN,&out.value))throw std::runtime_error("DPAPI protect failed");
  auto tmp=path_;tmp+=L"."+std::filesystem::path(new_device_id()).wstring()+L".tmp";
  HANDLE file=CreateFileW(tmp.c_str(),GENERIC_WRITE,0,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);
  if(file==INVALID_HANDLE_VALUE)throw std::runtime_error("vault temp create failed");
  DWORD written=0;BOOL ok=WriteFile(file,out.value.pbData,out.value.cbData,&written,nullptr);
  ok=ok && written==out.value.cbData && FlushFileBuffers(file);BOOL closed=CloseHandle(file);
  if(!ok || !closed){DeleteFileW(tmp.c_str());throw std::runtime_error("vault write failed");}
  if(!MoveFileExW(tmp.c_str(),path_.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH)){DeleteFileW(tmp.c_str());throw std::runtime_error("vault replace failed");}
 }
 std::string load() override {
  std::error_code ec;auto size=std::filesystem::file_size(path_,ec);
  if(ec||size==0||size>65536)throw std::runtime_error("vault unavailable or invalid");
  std::ifstream f(path_,std::ios::binary);if(!f)throw std::runtime_error("vault unavailable");
  std::vector<char>b(static_cast<size_t>(size));f.read(b.data(),static_cast<std::streamsize>(b.size()));if(!f || f.peek()!=std::ifstream::traits_type::eof())throw std::runtime_error("vault read failed");
  DATA_BLOB in{static_cast<DWORD>(b.size()),reinterpret_cast<BYTE*>(b.data())};BlobOwner out;
  if(!CryptUnprotectData(&in,nullptr,nullptr,nullptr,nullptr,CRYPTPROTECT_UI_FORBIDDEN,&out.value))throw std::runtime_error("DPAPI unprotect failed");
  if(out.value.cbData==0||out.value.cbData>1024)throw std::runtime_error("invalid credential");
  return std::string(reinterpret_cast<char*>(out.value.pbData),out.value.cbData);
 }
 void erase() override {std::filesystem::remove(path_);}
 bool exists() const override {std::error_code ec; bool found=std::filesystem::exists(path_,ec); if(ec)throw std::runtime_error("vault lookup failed"); return found;}
};
#else
class Unsupported final:public Vault {std::filesystem::path path_; public: bool available() const override {return false;} explicit Unsupported(std::filesystem::path p):path_(std::move(p)){} bool exists() const override {std::error_code ec;bool found=std::filesystem::exists(path_,ec);if(ec)throw std::runtime_error("vault lookup failed");return found;}void save(const std::string&)override{throw std::runtime_error("secure Windows DPAPI unavailable");}std::string load()override{throw std::runtime_error("secure Windows DPAPI unavailable");}void erase()override{}};
#endif
}
std::unique_ptr<Vault> make_vault(const std::filesystem::path& p){
#ifdef _WIN32
return std::make_unique<DPAPIVault>(p);
#else
return std::make_unique<Unsupported>(p);
#endif
}}
