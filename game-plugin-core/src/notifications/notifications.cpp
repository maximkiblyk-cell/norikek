#include "nori/core.hpp"
namespace nori {void Notifications::push(std::string text){if(text.size()>256)text.resize(256);if(items_.size()==8)items_.erase(items_.begin());items_.push_back({std::move(text)});}}
