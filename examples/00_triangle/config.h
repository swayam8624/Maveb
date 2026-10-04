//
// Created by Swayam Singal on 10/05/26.
//

#pragma once
#include <AppKit/AppKit.hpp>
#include <Metal/Metal.hpp>
#include <MetalKit/MetalKit.hpp>
#include <simd/simd.h>

#include <fstream>
#include <iostream>
#include <sstream>

struct Vertex {
    simd::float4 pos;   //(x,y)
    simd::float4 color; //(r,g,b)
};