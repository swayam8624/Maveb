#include <aether/reconstruction/ReferenceMarchingCubes.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <unordered_map>

#include <simd/simd.h>

namespace aether::reconstruction {
namespace {

// The classic topology table below is adapted from PoissonRecon's MarchingCubes.cpp.
// Copyright (c) 2006, Michael Kazhdan and Matthew Bolitho. BSD-3-Clause.
// The full attribution and license are recorded in THIRD_PARTY_NOTICES.md.

using Vec3 = std::array<double, 3>;

constexpr std::array<std::array<int, 3>, 8> cornerOffsets{{
    {{0, 0, 0}},
    {{1, 0, 0}},
    {{1, 1, 0}},
    {{0, 1, 0}},
    {{0, 0, 1}},
    {{1, 0, 1}},
    {{1, 1, 1}},
    {{0, 1, 1}},
}};

// PoissonRecon's table numbers the standard cube edges by axis first.
constexpr std::array<std::array<int, 2>, 12> edgeCorners{{
    {{0, 1}},
    {{3, 2}},
    {{4, 5}},
    {{7, 6}},
    {{0, 3}},
    {{1, 2}},
    {{4, 7}},
    {{5, 6}},
    {{0, 4}},
    {{1, 5}},
    {{3, 7}},
    {{2, 6}},
}};

// clang-format off
constexpr std::array<ReferenceMarchingCubes::CaseTriangles, 256> classicCases{{
	{  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   0,   4,   8,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   5,   0,   9,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   8,   9,   5,   8,   5,   4,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   1,   5,  11,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   0,   4,   8,   1,   5,  11,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   9,  11,   1,   9,   1,   0,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   8,   9,  11,   8,  11,   1,   8,   1,   4,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   4,   1,  10,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  10,   8,   0,  10,   0,   1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   5,   0,   9,   4,   1,  10,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  10,   8,   9,  10,   9,   5,  10,   5,   1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  11,  10,   4,  11,   4,   5,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  11,  10,   8,  11,   8,   0,  11,   0,   5,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   9,  11,  10,   9,  10,   4,   9,   4,   0,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   8,   9,  11,   8,  11,  10,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   8,   6,   2,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   6,   2,   0,   4,   6,   0,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   6,   2,   8,   5,   0,   9,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   5,   4,   6,   9,   5,   6,   2,   9,   6,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   1,   5,  11,   8,   6,   2,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   1,   5,  11,   6,   2,   0,   4,   6,   0,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   6,   2,   8,   9,  11,   1,   9,   1,   0,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   9,  11,   2,   2,  11,   1,   2,   1,   6,   6,   1,   4,  -1,  -1,  -1,  -1},
	{   1,  10,   4,   2,   8,   6,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   2,   0,   1,   6,   2,   1,  10,   6,   1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   5,   0,   9,   4,   1,  10,   8,   6,   2,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   5,   2,   9,   5,   6,   2,   5,   1,   6,   1,  10,   6,  -1,  -1,  -1,  -1},
	{   2,   8,   6,   4,   5,  11,   4,  11,  10,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   5,   2,   0,   6,   2,   5,  11,   6,   5,  10,   6,  11,  -1,  -1,  -1,  -1},
	{   9,  11,  10,   9,  10,   4,   9,   4,   0,   8,   6,   2,  -1,  -1,  -1,  -1},
	{   9,  11,   2,   2,  11,   6,  10,   6,  11,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   9,   2,   7,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   7,   9,   2,   4,   8,   0,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   0,   2,   7,   0,   7,   5,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   7,   5,   4,   2,   7,   4,   8,   2,   4,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   7,   9,   2,   5,  11,   1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   1,   5,  11,   0,   4,   8,   9,   2,   7,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   1,   0,   2,   1,   2,   7,   1,   7,  11,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   1,   7,  11,   1,   2,   7,   1,   4,   2,   4,   8,   2,  -1,  -1,  -1,  -1},
	{   4,   1,  10,   9,   2,   7,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   7,   9,   2,   0,   1,  10,   0,  10,   8,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   4,   1,  10,   2,   7,   5,   0,   2,   5,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   2,  10,   8,   1,  10,   2,   7,   1,   2,   5,   1,   7,  -1,  -1,  -1,  -1},
	{   7,   9,   2,  10,   4,   5,  11,  10,   5,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  11,  10,   8,  11,   8,   0,  11,   0,   5,   9,   2,   7,  -1,  -1,  -1,  -1},
	{  11,  10,   7,   7,  10,   4,   7,   4,   2,   2,   4,   0,  -1,  -1,  -1,  -1},
	{  11,  10,   7,   7,  10,   2,   8,   2,  10,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   7,   9,   8,   6,   7,   8,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   4,   6,   7,   0,   4,   7,   9,   0,   7,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   6,   7,   5,   8,   6,   5,   0,   8,   5,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   4,   6,   7,   5,   4,   7,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   5,  11,   1,   8,   6,   7,   9,   8,   7,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   4,   6,   7,   0,   4,   7,   9,   0,   7,  11,   1,   5,  -1,  -1,  -1,  -1},
	{   8,   1,   0,  11,   1,   8,   6,  11,   8,   7,  11,   6,  -1,  -1,  -1,  -1},
	{  11,   6,   7,   1,   6,  11,   6,   1,   4,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   1,  10,   4,   6,   7,   9,   6,   9,   8,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   0,   1,   9,   9,   1,  10,   9,  10,   7,   7,  10,   6,  -1,  -1,  -1,  -1},
	{   6,   7,   5,   8,   6,   5,   0,   8,   5,   1,  10,   4,  -1,  -1,  -1,  -1},
	{   1,   7,   5,  10,   7,   1,   7,  10,   6,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  11,  10,   4,  11,   4,   5,   7,   9,   8,   6,   7,   8,  -1,  -1,  -1,  -1},
	{   0,   6,   9,   9,   6,   7,   6,   0,   5,   5,  11,  10,   5,  10,   6,  -1},
	{   8,   7,   0,   6,   7,   8,   4,   0,   7,  11,  10,   4,   7,  11,   4,  -1},
	{  11,  10,   6,  11,   6,   7,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  11,   7,   3,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   0,   4,   8,  11,   7,   3,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   9,   5,   0,  11,   7,   3,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  11,   7,   3,   4,   8,   9,   5,   4,   9,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   3,   1,   5,   3,   5,   7,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   0,   4,   8,   7,   3,   1,   5,   7,   1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   3,   1,   0,   3,   0,   9,   3,   9,   7,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   7,   8,   9,   4,   8,   7,   3,   4,   7,   1,   4,   3,  -1,  -1,  -1,  -1},
	{   1,  10,   4,   3,  11,   7,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   3,  11,   7,   8,   0,   1,  10,   8,   1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   4,   1,  10,   5,   0,   9,  11,   7,   3,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  10,   8,   9,  10,   9,   5,  10,   5,   1,  11,   7,   3,  -1,  -1,  -1,  -1},
	{   4,   5,   7,   4,   7,   3,   4,   3,  10,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  10,   8,   3,   3,   8,   0,   3,   0,   7,   7,   0,   5,  -1,  -1,  -1,  -1},
	{   4,   3,  10,   4,   7,   3,   4,   0,   7,   0,   9,   7,  -1,  -1,  -1,  -1},
	{  10,   8,   3,   3,   8,   7,   9,   7,   8,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  11,   7,   3,   8,   6,   2,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  11,   7,   3,   2,   0,   4,   2,   4,   6,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  11,   7,   3,   8,   6,   2,   5,   0,   9,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   5,   4,   6,   9,   5,   6,   2,   9,   6,   3,  11,   7,  -1,  -1,  -1,  -1},
	{   8,   6,   2,   3,   1,   5,   3,   5,   7,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   3,   1,   5,   3,   5,   7,   6,   2,   0,   4,   6,   0,  -1,  -1,  -1,  -1},
	{   3,   1,   0,   3,   0,   9,   3,   9,   7,   2,   8,   6,  -1,  -1,  -1,  -1},
	{   9,   4,   2,   2,   4,   6,   4,   9,   7,   7,   3,   1,   7,   1,   4,  -1},
	{   8,   6,   2,  11,   7,   3,   4,   1,  10,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   2,   0,   1,   6,   2,   1,  10,   6,   1,  11,   7,   3,  -1,  -1,  -1,  -1},
	{   5,   0,   9,   4,   1,  10,   8,   6,   2,  11,   7,   3,  -1,  -1,  -1,  -1},
	{  11,   7,   3,   5,   2,   9,   5,   6,   2,   5,   1,   6,   1,  10,   6,  -1},
	{   4,   5,   7,   4,   7,   3,   4,   3,  10,   6,   2,   8,  -1,  -1,  -1,  -1},
	{  10,   5,   3,   3,   5,   7,   5,  10,   6,   6,   2,   0,   6,   0,   5,  -1},
	{   8,   6,   2,   4,   3,  10,   4,   7,   3,   4,   0,   7,   0,   9,   7,  -1},
	{   9,   7,  10,  10,   7,   3,  10,   6,   9,   6,   2,   9,  -1,  -1,  -1,  -1},
	{   3,  11,   9,   2,   3,   9,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   4,   8,   0,   2,   3,  11,   2,  11,   9,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   0,   2,   3,   0,   3,  11,   0,  11,   5,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   2,   3,   8,   8,   3,  11,   8,  11,   4,   4,  11,   5,  -1,  -1,  -1,  -1},
	{   2,   3,   1,   2,   1,   5,   2,   5,   9,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   2,   3,   1,   2,   1,   5,   2,   5,   9,   0,   4,   8,  -1,  -1,  -1,  -1},
	{   0,   2,   3,   0,   3,   1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   2,   3,   8,   8,   3,   4,   1,   4,   3,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   1,  10,   4,   9,   2,   3,  11,   9,   3,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  10,   8,   0,  10,   0,   1,   3,  11,   9,   2,   3,   9,  -1,  -1,  -1,  -1},
	{   0,   2,   3,   0,   3,  11,   0,  11,   5,   1,  10,   4,  -1,  -1,  -1,  -1},
	{   5,   2,  11,  11,   2,   3,   2,   5,   1,   1,  10,   8,   1,   8,   2,  -1},
	{  10,   2,   3,   9,   2,  10,   4,   9,  10,   5,   9,   4,  -1,  -1,  -1,  -1},
	{   5,  10,   0,   0,  10,   8,  10,   5,   9,   9,   2,   3,   9,   3,  10,  -1},
	{   0,   2,   4,   4,   2,  10,   3,  10,   2,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  10,   8,   2,  10,   2,   3,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  11,   9,   8,   3,  11,   8,   6,   3,   8,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   0,  11,   9,   3,  11,   0,   4,   3,   0,   6,   3,   4,  -1,  -1,  -1,  -1},
	{  11,   5,   3,   5,   0,   3,   0,   6,   3,   0,   8,   6,  -1,  -1,  -1,  -1},
	{   3,   4,   6,  11,   4,   3,   4,  11,   5,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   3,   1,   6,   6,   1,   5,   6,   5,   8,   8,   5,   9,  -1,  -1,  -1,  -1},
	{   0,   6,   9,   4,   6,   0,   5,   9,   6,   3,   1,   5,   6,   3,   5,  -1},
	{   3,   1,   6,   6,   1,   8,   0,   8,   1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   3,   1,   4,   3,   4,   6,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  11,   9,   8,   3,  11,   8,   6,   3,   8,   4,   1,  10,  -1,  -1,  -1,  -1},
	{   3,   9,   6,  11,   9,   3,  10,   6,   9,   0,   1,  10,   9,   0,  10,  -1},
	{   4,   1,  10,  11,   5,   3,   5,   0,   3,   0,   6,   3,   0,   8,   6,  -1},
	{   5,  10,   6,   1,  10,   5,   6,  11,   5,   6,   3,  11,  -1,  -1,  -1,  -1},
	{  10,   5,   3,   4,   5,  10,   6,   3,   5,   9,   8,   6,   5,   9,   6,  -1},
	{   6,   3,  10,   9,   0,   5,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   3,  10,   0,   0,  10,   4,   0,   8,   3,   8,   6,   3,  -1,  -1,  -1,  -1},
	{   6,   3,  10,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  10,   3,   6,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   3,   6,  10,   0,   4,   8,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   5,   0,   9,  10,   3,   6,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   3,   6,  10,   8,   9,   5,   8,   5,   4,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  11,   1,   5,  10,   3,   6,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   0,   4,   8,   1,   5,  11,  10,   3,   6,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  10,   3,   6,   0,   9,  11,   1,   0,  11,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   8,   9,  11,   8,  11,   1,   8,   1,   4,  10,   3,   6,  -1,  -1,  -1,  -1},
	{   4,   1,   3,   6,   4,   3,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   0,   1,   3,   8,   0,   3,   6,   8,   3,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   5,   0,   9,   3,   6,   4,   1,   3,   4,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   8,   9,   6,   6,   9,   5,   6,   5,   3,   3,   5,   1,  -1,  -1,  -1,  -1},
	{   6,   4,   5,   6,   5,  11,   6,  11,   3,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   0,   6,   8,   0,   3,   6,   0,   5,   3,   5,  11,   3,  -1,  -1,  -1,  -1},
	{   3,   9,  11,   0,   9,   3,   6,   0,   3,   4,   0,   6,  -1,  -1,  -1,  -1},
	{   8,   9,   6,   6,   9,   3,  11,   3,   9,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   2,   8,  10,   3,   2,  10,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   3,   2,   0,  10,   3,   0,   4,  10,   0,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   5,   0,   9,   8,  10,   3,   8,   3,   2,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   9,   3,   2,  10,   3,   9,   5,  10,   9,   4,  10,   5,  -1,  -1,  -1,  -1},
	{  11,   1,   5,   2,   8,  10,   3,   2,  10,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   3,   2,   0,  10,   3,   0,   4,  10,   0,   5,  11,   1,  -1,  -1,  -1,  -1},
	{   9,  11,   1,   9,   1,   0,   2,   8,  10,   3,   2,  10,  -1,  -1,  -1,  -1},
	{  10,   2,   4,   3,   2,  10,   1,   4,   2,   9,  11,   1,   2,   9,   1,  -1},
	{   1,   3,   2,   4,   1,   2,   8,   4,   2,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   0,   1,   3,   2,   0,   3,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   1,   3,   2,   4,   1,   2,   8,   4,   2,   9,   5,   0,  -1,  -1,  -1,  -1},
	{   9,   3,   2,   5,   3,   9,   3,   5,   1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   3,   2,  11,  11,   2,   8,  11,   8,   5,   5,   8,   4,  -1,  -1,  -1,  -1},
	{   5,   2,   0,  11,   2,   5,   2,  11,   3,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   4,   3,   8,   8,   3,   2,   3,   4,   0,   0,   9,  11,   0,  11,   3,  -1},
	{   9,  11,   3,   9,   3,   2,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  10,   3,   6,   9,   2,   7,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   9,   2,   7,  10,   3,   6,   0,   4,   8,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  10,   3,   6,   7,   5,   0,   7,   0,   2,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   7,   5,   4,   2,   7,   4,   8,   2,   4,  10,   3,   6,  -1,  -1,  -1,  -1},
	{  10,   3,   6,   9,   2,   7,   1,   5,  11,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  10,   3,   6,   9,   2,   7,   1,   5,  11,   0,   4,   8,  -1,  -1,  -1,  -1},
	{   1,   0,   2,   1,   2,   7,   1,   7,  11,   3,   6,  10,  -1,  -1,  -1,  -1},
	{  10,   3,   6,   1,   7,  11,   1,   2,   7,   1,   4,   2,   4,   8,   2,  -1},
	{   9,   2,   7,   6,   4,   1,   6,   1,   3,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   0,   1,   3,   8,   0,   3,   6,   8,   3,   7,   9,   2,  -1,  -1,  -1,  -1},
	{   0,   2,   7,   0,   7,   5,   4,   1,   3,   6,   4,   3,  -1,  -1,  -1,  -1},
	{   2,   5,   8,   7,   5,   2,   6,   8,   5,   1,   3,   6,   5,   1,   6,  -1},
	{   6,   4,   5,   6,   5,  11,   6,  11,   3,   7,   9,   2,  -1,  -1,  -1,  -1},
	{   9,   2,   7,   0,   6,   8,   0,   3,   6,   0,   5,   3,   5,  11,   3,  -1},
	{   3,   4,  11,   6,   4,   3,   7,  11,   4,   0,   2,   7,   4,   0,   7,  -1},
	{  11,   3,   8,   8,   3,   6,   8,   2,  11,   2,   7,  11,  -1,  -1,  -1,  -1},
	{   9,   8,  10,   7,   9,  10,   3,   7,  10,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   9,   0,   7,   0,   4,   7,   4,   3,   7,   4,  10,   3,  -1,  -1,  -1,  -1},
	{   8,  10,   0,   0,  10,   3,   0,   3,   5,   5,   3,   7,  -1,  -1,  -1,  -1},
	{  10,   5,   4,   3,   5,  10,   5,   3,   7,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   9,   8,  10,   7,   9,  10,   3,   7,  10,   1,   5,  11,  -1,  -1,  -1,  -1},
	{   1,   5,  11,   9,   0,   7,   0,   4,   7,   4,   3,   7,   4,  10,   3,  -1},
	{  11,   0,   7,   1,   0,  11,   3,   7,   0,   8,  10,   3,   0,   8,   3,  -1},
	{   7,   1,   4,  11,   1,   7,   4,   3,   7,   4,  10,   3,  -1,  -1,  -1,  -1},
	{   4,   9,   8,   7,   9,   4,   1,   7,   4,   3,   7,   1,  -1,  -1,  -1,  -1},
	{   7,   1,   3,   9,   1,   7,   1,   9,   0,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   8,   7,   0,   0,   7,   5,   7,   8,   4,   4,   1,   3,   4,   3,   7,  -1},
	{   5,   1,   3,   7,   5,   3,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   3,   4,  11,  11,   4,   5,   4,   3,   7,   7,   9,   8,   7,   8,   4,  -1},
	{   3,   9,   0,   7,   9,   3,   0,  11,   3,   0,   5,  11,  -1,  -1,  -1,  -1},
	{   3,   7,  11,   8,   4,   0,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   3,   7,  11,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   6,  10,  11,   7,   6,  11,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   0,   4,   8,  10,  11,   7,  10,   7,   6,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   9,   5,   0,   6,  10,  11,   7,   6,  11,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   8,   9,   5,   8,   5,   4,   6,  10,  11,   7,   6,  11,  -1,  -1,  -1,  -1},
	{   5,   7,   6,   5,   6,  10,   5,  10,   1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   5,   7,   6,   5,   6,  10,   5,  10,   1,   4,   8,   0,  -1,  -1,  -1,  -1},
	{   1,   0,  10,  10,   0,   9,  10,   9,   6,   6,   9,   7,  -1,  -1,  -1,  -1},
	{   1,   7,  10,  10,   7,   6,   7,   1,   4,   4,   8,   9,   4,   9,   7,  -1},
	{   7,   6,   4,   7,   4,   1,   7,   1,  11,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  11,   0,   1,   8,   0,  11,   7,   8,  11,   6,   8,   7,  -1,  -1,  -1,  -1},
	{   7,   6,   4,   7,   4,   1,   7,   1,  11,   5,   0,   9,  -1,  -1,  -1,  -1},
	{  11,   6,   1,   7,   6,  11,   5,   1,   6,   8,   9,   5,   6,   8,   5,  -1},
	{   4,   5,   7,   4,   7,   6,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   5,   7,   0,   0,   7,   8,   6,   8,   7,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   7,   6,   9,   9,   6,   0,   4,   0,   6,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   8,   9,   7,   8,   7,   6,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   8,  10,  11,   2,   8,  11,   7,   2,  11,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  10,  11,   4,   4,  11,   7,   4,   7,   0,   0,   7,   2,  -1,  -1,  -1,  -1},
	{   8,  10,  11,   2,   8,  11,   7,   2,  11,   5,   0,   9,  -1,  -1,  -1,  -1},
	{   9,   4,   2,   5,   4,   9,   7,   2,   4,  10,  11,   7,   4,  10,   7,  -1},
	{   1,   8,  10,   2,   8,   1,   5,   2,   1,   7,   2,   5,  -1,  -1,  -1,  -1},
	{   1,   7,  10,   5,   7,   1,   4,  10,   7,   2,   0,   4,   7,   2,   4,  -1},
	{   7,   1,   9,   9,   1,   0,   1,   7,   2,   2,   8,  10,   2,  10,   1,  -1},
	{   7,   2,   9,  10,   1,   4,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   8,   4,   2,   4,   1,   2,   1,   7,   2,   1,  11,   7,  -1,  -1,  -1,  -1},
	{  11,   0,   1,   7,   0,  11,   0,   7,   2,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   5,   0,   9,   8,   4,   2,   4,   1,   2,   1,   7,   2,   1,  11,   7,  -1},
	{   2,   5,   1,   9,   5,   2,   1,   7,   2,   1,  11,   7,  -1,  -1,  -1,  -1},
	{   4,   5,   8,   8,   5,   2,   7,   2,   5,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   7,   2,   0,   5,   7,   0,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   7,   2,   4,   4,   2,   8,   4,   0,   7,   0,   9,   7,  -1,  -1,  -1,  -1},
	{   7,   2,   9,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  10,  11,   9,   6,  10,   9,   2,   6,   9,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  10,  11,   9,   6,  10,   9,   2,   6,   9,   0,   4,   8,  -1,  -1,  -1,  -1},
	{   5,  10,  11,   6,  10,   5,   0,   6,   5,   2,   6,   0,  -1,  -1,  -1,  -1},
	{   2,   5,   8,   8,   5,   4,   5,   2,   6,   6,  10,  11,   6,  11,   5,  -1},
	{  10,   1,   6,   1,   5,   6,   5,   2,   6,   5,   9,   2,  -1,  -1,  -1,  -1},
	{   0,   4,   8,  10,   1,   6,   1,   5,   6,   5,   2,   6,   5,   9,   2,  -1},
	{   1,   0,  10,  10,   0,   6,   2,   6,   0,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   2,   6,   1,   1,   6,  10,   1,   4,   2,   4,   8,   2,  -1,  -1,  -1,  -1},
	{  11,   9,   1,   1,   9,   2,   1,   2,   4,   4,   2,   6,  -1,  -1,  -1,  -1},
	{   8,   1,   6,   0,   1,   8,   2,   6,   1,  11,   9,   2,   1,  11,   2,  -1},
	{  11,   6,   1,   1,   6,   4,   6,  11,   5,   5,   0,   2,   5,   2,   6,  -1},
	{   2,   6,   8,  11,   5,   1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   6,   4,   2,   2,   4,   9,   5,   9,   4,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   5,   9,   6,   6,   9,   2,   6,   8,   5,   8,   0,   5,  -1,  -1,  -1,  -1},
	{   0,   2,   6,   0,   6,   4,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   2,   6,   8,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   8,  10,  11,   9,   8,  11,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   0,  11,   9,   4,  11,   0,  11,   4,  10,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   5,  10,  11,   0,  10,   5,  10,   0,   8,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   4,  10,  11,   5,   4,  11,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   1,   8,  10,   5,   8,   1,   8,   5,   9,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   9,   4,  10,   0,   4,   9,  10,   5,   9,  10,   1,   5,  -1,  -1,  -1,  -1},
	{   0,   8,  10,   1,   0,  10,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  10,   1,   4,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   4,   9,   8,   1,   9,   4,   9,   1,  11,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   1,  11,   9,   0,   1,   9,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  11,   0,   8,   5,   0,  11,   8,   1,  11,   8,   4,   1,  -1,  -1,  -1,  -1},
	{  11,   5,   1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   5,   9,   8,   4,   5,   8,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   9,   0,   5,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{   8,   4,   0,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1},
	{  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1,  -1}
}};
// clang-format on

std::size_t gridIndex(const DenseTsdfConfig& config, std::uint32_t x, std::uint32_t y,
                      std::uint32_t z) {
    return (static_cast<std::size_t>(z) * config.dimensions[1] + y) * config.dimensions[0] + x;
}

Vec3 add(const Vec3& left, const Vec3& right) {
    return {left[0] + right[0], left[1] + right[1], left[2] + right[2]};
}

Vec3 subtract(const Vec3& left, const Vec3& right) {
    return {left[0] - right[0], left[1] - right[1], left[2] - right[2]};
}

Vec3 scale(const Vec3& value, double factor) {
    return {value[0] * factor, value[1] * factor, value[2] * factor};
}

double dot(const Vec3& left, const Vec3& right) {
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2];
}

Vec3 cross(const Vec3& left, const Vec3& right) {
    return {
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    };
}

Vec3 normalized(const Vec3& value) {
    const auto length = std::sqrt(dot(value, value));
    return length > 1.0e-12 ? scale(value, 1.0 / length) : Vec3{0.0, 0.0, 1.0};
}

Result<void> validateField(const DenseTsdfConfig& config, std::span<const TsdfVoxel> voxels) {
    const auto xy = static_cast<std::size_t>(config.dimensions[0]) * config.dimensions[1];
    if (config.dimensions[0] < 2 || config.dimensions[1] < 2 || config.dimensions[2] < 2 ||
        xy / config.dimensions[0] != config.dimensions[1] ||
        config.dimensions[2] > std::numeric_limits<std::size_t>::max() / xy ||
        voxels.size() != xy * config.dimensions[2] || !std::isfinite(config.voxelSizeMetres) ||
        config.voxelSizeMetres <= 0.0)
        return fail(ErrorCode::invalidArgument, "Reference Marching Cubes field is invalid");
    for (const auto& origin : config.originMetres)
        if (!std::isfinite(origin))
            return fail(ErrorCode::invalidArgument,
                        "Reference Marching Cubes origin is non-finite");
    for (const auto& voxel : voxels)
        if (!std::isfinite(voxel.distance) || !std::isfinite(voxel.weight) || voxel.weight < 0.0F)
            return fail(ErrorCode::invalidArgument, "Reference Marching Cubes samples are invalid");
    return {};
}

} // namespace

const ReferenceMarchingCubes::CaseTriangles&
ReferenceMarchingCubes::caseTriangles(std::uint8_t caseIndex) noexcept {
    return classicCases[caseIndex];
}

Result<mesh::MeshAsset> ReferenceMarchingCubes::extract(const DenseTsdfConfig& config,
                                                        std::span<const TsdfVoxel> voxels) {
    if (auto valid = validateField(config, voxels); !valid)
        return std::unexpected(valid.error());

    mesh::MeshAsset asset;
    asset.name = "reference-marching-cubes";
    mesh::MeshPrimitive primitive;
    primitive.name = "reference-surface";
    std::unordered_map<std::uint64_t, std::uint32_t> edgeVertices;

    const auto position = [&](std::uint32_t x, std::uint32_t y, std::uint32_t z) -> Vec3 {
        return {
            config.originMetres[0] + static_cast<double>(x) * config.voxelSizeMetres,
            config.originMetres[1] + static_cast<double>(y) * config.voxelSizeMetres,
            config.originMetres[2] + static_cast<double>(z) * config.voxelSizeMetres,
        };
    };
    const auto gradient = [&](std::uint32_t x, std::uint32_t y, std::uint32_t z) -> Vec3 {
        const auto lowX = x == 0 ? x : x - 1;
        const auto highX = std::min(x + 1, config.dimensions[0] - 1);
        const auto lowY = y == 0 ? y : y - 1;
        const auto highY = std::min(y + 1, config.dimensions[1] - 1);
        const auto lowZ = z == 0 ? z : z - 1;
        const auto highZ = std::min(z + 1, config.dimensions[2] - 1);
        return normalized({
            static_cast<double>(voxels[gridIndex(config, highX, y, z)].distance -
                                voxels[gridIndex(config, lowX, y, z)].distance),
            static_cast<double>(voxels[gridIndex(config, x, highY, z)].distance -
                                voxels[gridIndex(config, x, lowY, z)].distance),
            static_cast<double>(voxels[gridIndex(config, x, y, highZ)].distance -
                                voxels[gridIndex(config, x, y, lowZ)].distance),
        });
    };

    for (std::uint32_t z = 0; z + 1 < config.dimensions[2]; ++z) {
        for (std::uint32_t y = 0; y + 1 < config.dimensions[1]; ++y) {
            for (std::uint32_t x = 0; x + 1 < config.dimensions[0]; ++x) {
                std::array<const TsdfVoxel*, 8> corners{};
                std::uint8_t caseIndex = 0;
                bool observed = true;
                for (std::size_t corner = 0; corner < corners.size(); ++corner) {
                    const auto cx = x + static_cast<std::uint32_t>(cornerOffsets[corner][0]);
                    const auto cy = y + static_cast<std::uint32_t>(cornerOffsets[corner][1]);
                    const auto cz = z + static_cast<std::uint32_t>(cornerOffsets[corner][2]);
                    corners[corner] = &voxels[gridIndex(config, cx, cy, cz)];
                    observed = observed && corners[corner]->weight > 0.0F;
                    if (corners[corner]->distance < 0.0F)
                        caseIndex |= static_cast<std::uint8_t>(1U << corner);
                }
                if (!observed || caseIndex == 0 || caseIndex == 255)
                    continue;

                const auto vertexForEdge = [&](int edge) -> std::uint32_t {
                    const auto a = edgeCorners[static_cast<std::size_t>(edge)][0];
                    const auto b = edgeCorners[static_cast<std::size_t>(edge)][1];
                    const auto& offsetA = cornerOffsets[static_cast<std::size_t>(a)];
                    const auto& offsetB = cornerOffsets[static_cast<std::size_t>(b)];
                    const auto ax = x + static_cast<std::uint32_t>(offsetA[0]);
                    const auto ay = y + static_cast<std::uint32_t>(offsetA[1]);
                    const auto az = z + static_cast<std::uint32_t>(offsetA[2]);
                    const auto bx = x + static_cast<std::uint32_t>(offsetB[0]);
                    const auto by = y + static_cast<std::uint32_t>(offsetB[1]);
                    const auto bz = z + static_cast<std::uint32_t>(offsetB[2]);
                    const auto lowX = std::min(ax, bx);
                    const auto lowY = std::min(ay, by);
                    const auto lowZ = std::min(az, bz);
                    const std::uint64_t pointIndex =
                        (static_cast<std::uint64_t>(lowZ) * config.dimensions[1] + lowY) *
                            config.dimensions[0] +
                        lowX;
                    const std::uint64_t axis = ax != bx ? 0 : (ay != by ? 1 : 2);
                    const auto key = pointIndex * 3 + axis;
                    if (const auto found = edgeVertices.find(key); found != edgeVertices.end())
                        return found->second;

                    const auto valueA =
                        static_cast<double>(corners[static_cast<std::size_t>(a)]->distance);
                    const auto valueB =
                        static_cast<double>(corners[static_cast<std::size_t>(b)]->distance);
                    const auto denominator = valueA - valueB;
                    const auto t = std::abs(denominator) > 1.0e-12
                                       ? std::clamp(valueA / denominator, 0.0, 1.0)
                                       : 0.5;
                    const auto point =
                        add(position(ax, ay, az),
                            scale(subtract(position(bx, by, bz), position(ax, ay, az)), t));
                    const auto normal = normalized(
                        add(scale(gradient(ax, ay, az), 1.0 - t), scale(gradient(bx, by, bz), t)));
                    std::array<float, 3> color{};
                    for (std::size_t channel = 0; channel < color.size(); ++channel)
                        color[channel] = static_cast<float>(
                            static_cast<double>(
                                corners[static_cast<std::size_t>(a)]->color[channel]) *
                                (1.0 - t) +
                            static_cast<double>(
                                corners[static_cast<std::size_t>(b)]->color[channel]) *
                                t);

                    mesh::MeshVertex vertex{};
                    vertex.position =
                        simd_make_float3(static_cast<float>(point[0]), static_cast<float>(point[1]),
                                         static_cast<float>(point[2]));
                    vertex.normal = simd_make_float3(static_cast<float>(normal[0]),
                                                     static_cast<float>(normal[1]),
                                                     static_cast<float>(normal[2]));
                    vertex.tangent = simd_make_float4(1.0F, 0.0F, 0.0F, 1.0F);
                    const auto result = static_cast<std::uint32_t>(primitive.vertices.size());
                    primitive.vertices.push_back(vertex);
                    primitive.vertexColors.push_back(
                        simd_make_float3(color[0], color[1], color[2]));
                    edgeVertices.emplace(key, result);
                    return result;
                };

                const auto& triangles = classicCases[caseIndex];
                for (std::size_t entry = 0; entry + 2 < triangles.size() && triangles[entry] >= 0;
                     entry += 3) {
                    auto a = vertexForEdge(triangles[entry]);
                    auto b = vertexForEdge(triangles[entry + 1]);
                    auto c = vertexForEdge(triangles[entry + 2]);
                    const auto& pa = primitive.vertices[a].position;
                    const auto& pb = primitive.vertices[b].position;
                    const auto& pc = primitive.vertices[c].position;
                    const Vec3 faceNormal =
                        cross({static_cast<double>(pb.x - pa.x), static_cast<double>(pb.y - pa.y),
                               static_cast<double>(pb.z - pa.z)},
                              {static_cast<double>(pc.x - pa.x), static_cast<double>(pc.y - pa.y),
                               static_cast<double>(pc.z - pa.z)});
                    const Vec3 averageNormal =
                        add({primitive.vertices[a].normal.x, primitive.vertices[a].normal.y,
                             primitive.vertices[a].normal.z},
                            add({primitive.vertices[b].normal.x, primitive.vertices[b].normal.y,
                                 primitive.vertices[b].normal.z},
                                {primitive.vertices[c].normal.x, primitive.vertices[c].normal.y,
                                 primitive.vertices[c].normal.z}));
                    if (dot(faceNormal, averageNormal) < 0.0)
                        std::swap(b, c);
                    primitive.indices.insert(primitive.indices.end(), {a, b, c});
                }
            }
        }
    }

    if (primitive.vertices.empty())
        return fail(ErrorCode::notFound,
                    "Reference scalar field contains no observed zero crossing");
    primitive.materialIndex = 0;
    asset.primitives.push_back(std::move(primitive));
    mesh::SceneNode node;
    node.name = "reference-root";
    asset.nodes.push_back(node);
    mesh::MeshInstance instance;
    instance.name = "reference-instance";
    instance.primitiveIndex = 0;
    instance.nodeIndex = 0;
    asset.instances.push_back(instance);
    return asset;
}

} // namespace aether::reconstruction
