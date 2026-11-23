#pragma once
#include "nori/core.hpp"
#include <cairo/cairo.h>
void render(cairo_t*,int,int,const nori::Core&,const std::string&);
