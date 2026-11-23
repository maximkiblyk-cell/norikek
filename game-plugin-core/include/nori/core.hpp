#pragma once
#include <string>
#include <vector>
#include <filesystem>
#include <optional>
#include <memory>
#include <atomic>
#include <future>
#include <chrono>
#include <mutex>
#include <functional>
#include <cstdint>
#include <nlohmann/json.hpp>
namespace nori {
using json=nlohmann::json;
enum class Screen {Dashboard,Messages,Advertisements,Items,Automation,Telegram,License,Settings};
enum class ViewState {Loading,Empty,Success,Error,Offline,Disabled,NotConnected};
const std::vector<std::string>& screen_names();
const char* state_name(ViewState s);
struct Settings { int version=1; std::string device_id; std::string hotkey="Insert"; int ui_scale=100; bool notifications=true; bool reduced_motion=false; };
std::string new_device_id();
class SettingsStore { std::filesystem::path path_; public: explicit SettingsStore(std::filesystem::path p):path_(std::move(p)){} Settings load() const; void save(const Settings&) const; Settings reset() const; };
class Navigation { Screen current_=Screen::Dashboard; public: Screen current()const{return current_;} void select(Screen s){current_=s;} };
class Input { bool open_=true; bool held_=false; public: bool key(bool down, const std::string& key,const std::string& configured); bool open()const{return open_;} };
struct HttpRequest {std::string method="GET",url,body,bearer,ca_file; long connect_timeout_ms=2000, timeout_ms=5000; unsigned retries=2;};
struct HttpResponse {long status=0; std::string body; std::string error; bool cancelled=false;};
class RequestHandle { std::shared_ptr<std::atomic_bool> stop_; std::future<HttpResponse> future_; public: RequestHandle(std::shared_ptr<std::atomic_bool> s,std::future<HttpResponse>&& f):stop_(std::move(s)),future_(std::move(f)){} RequestHandle(RequestHandle&&)=default; RequestHandle& operator=(RequestHandle&&)=default; void cancel(){stop_->store(true);} bool ready(); HttpResponse get(){return future_.get();} };
class HttpClient {public: HttpResponse perform(const HttpRequest&,const std::atomic_bool&)const; RequestHandle async(HttpRequest r)const;};
class Vault {public: virtual ~Vault()=default; virtual void save(const std::string&)=0; virtual std::string load()=0; virtual void erase()=0; virtual bool exists() const {return true;} virtual bool available() const {return true;}};
std::unique_ptr<Vault> make_vault(const std::filesystem::path& path);
struct Pairing {std::string id,code,claim_secret,expires,device_id;};
class V2Api {std::string base_, ca_file_; const HttpClient& http_; public: V2Api(std::string b,const HttpClient& h,std::string ca_file={}):base_(std::move(b)),ca_file_(std::move(ca_file)),http_(h){} Pairing start(const Settings&,const std::string& platform,const std::string& name,const std::atomic_bool&)const; std::string claim(Pairing&,Vault&,const std::atomic_bool&)const; HttpResponse access(const std::string& credential,const std::atomic_bool&)const; };
class LegacyV06 {std::string base_; const HttpClient& http_; public: LegacyV06(std::string b,const HttpClient& h):base_(std::move(b)),http_(h){} HttpResponse health(const std::atomic_bool&)const; HttpResponse device_me(const std::string& credential,const std::atomic_bool&)const;};
class LicenseGate {bool online_=false, verified_=false; std::chrono::steady_clock::time_point deadline_{}; public: void offline(){online_=false;verified_=false;} bool apply_v2(const HttpResponse&); bool permits()const; std::chrono::steady_clock::time_point deadline()const{return deadline_;} bool online()const{return online_ && verified_ && std::chrono::steady_clock::now()<deadline_;} };
enum class ConnectionState {Unpaired, WaitingConfirmation, Connecting, Online, Offline, Denied, Revoked, Error};
const char* connection_name(ConnectionState);
struct LicenseInfo {std::string platform, expires_at, device_id;};
// Calls perform I/O synchronously: invoke on a worker thread, never the render thread.
// Single-thread ownership: do not call methods concurrently.
class ClientSession {
  V2Api api_; Vault& vault_; LicenseGate& gate_; std::optional<Pairing> pairing_; ConnectionState state_=ConnectionState::Unpaired; LicenseInfo info_;
public:
  ClientSession(std::string base,const HttpClient& http,Vault& vault,LicenseGate& gate,std::string ca_file={}) : api_(std::move(base),http,std::move(ca_file)),vault_(vault),gate_(gate) {}
  ~ClientSession();
  ClientSession(const ClientSession&)=delete;
  ClientSession& operator=(const ClientSession&)=delete;
  std::string begin(const Settings&,const std::string& platform,const std::string& name,const std::atomic_bool&);
  bool complete(const std::atomic_bool&); // false while awaiting user's Telegram confirmation
  bool refresh(const std::atomic_bool&); // call after startup/reconnect; fail closed on any error
  void disconnect(){gate_.offline();state_=ConnectionState::Offline;}
  ConnectionState state()const{return state_;}
  std::string pairing_expiry()const{return pairing_?pairing_->expires:std::string{};}
  LicenseInfo info()const{return info_;}
  void cancel_pairing();
};
// Equal jitter: delay is in [half of capped exponential, capped exponential].
class RetryBackoff {
 unsigned attempt_=0;
public:
 std::chrono::milliseconds next(std::uint32_t sample);
 void reset(){attempt_=0;}
};
struct AuthView { ConnectionState state=ConnectionState::Unpaired; std::string code, code_expires, platform, license_expires, device_id, detail; bool busy=false, can_pair=false, retry_scheduled=false; };
class AuthController {
 struct Impl; std::unique_ptr<Impl> impl_;
public:
 AuthController(std::string, const Settings&, std::unique_ptr<Vault>, std::string ca_file={});
 ~AuthController(); AuthController(const AuthController&)=delete; AuthController& operator=(const AuthController&)=delete;
 bool begin(const std::string& platform); bool complete(); bool refresh(); void cancel(); void shutdown(); AuthView view()const;
};
enum class LogCode {Started,Stopped,SettingsSaved,NetworkError,Unauthorized,StorageError};
class Logger {std::filesystem::path path_; std::mutex mutex_; public:explicit Logger(std::filesystem::path p):path_(std::move(p)){} void event(LogCode);};
struct Notification {std::string text;};
class Notifications {std::vector<Notification> items_; public: void push(std::string); const auto& items()const{return items_;}};
class Adapter {public:virtual ~Adapter()=default;virtual const char* name()const=0; virtual bool connected()const=0;};
std::vector<std::unique_ptr<Adapter>> adapters();
class Core {SettingsStore store_; bool running_=false; std::unique_ptr<AuthController> auth_; public: Settings settings; Navigation nav; Input input; LicenseGate license; Notifications notifications; explicit Core(std::filesystem::path p):store_(std::move(p)){} void start(); void stop(); void configure_auth(std::string, std::unique_ptr<Vault>, std::string ca={}); AuthController* auth()const{return auth_.get();} bool running()const{return running_;} void save(); void reset(); ViewState state(Screen)const;};
}
