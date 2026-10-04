//
// Created by Swayam Singal on 10/05/26.
//

#pragma once
#include "../config.h"

class Renderer {
  public:
    Renderer(MTL::Device* device);
    ~Renderer();
    void draw(MTK::View* view);

  private:
    void buildMeshes();
    void buildShaders();
    MTL::RenderPipelineState* buildShader(const char* filename, const char* vertName,
                                          const char* fragName);
    MTL::Device* device;
    MTL::CommandQueue* commandQueue;
    /*
     A render pipeline is in charge of standard graphics operations.
     Compute pipelines can also be made, but not today.
    */
    MTL::RenderPipelineState *trianglePipeline, *generalPipeline;
    MTL::Buffer* triangleMesh;
};