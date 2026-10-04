//
// Created by Swayam Singal on 10/05/26.
//

#pragma once
#include "../config.h"
#include "../view/renderer.h"
class ViewDelegate : public MTK::ViewDelegate {
  public:
    ViewDelegate(MTL::Device* device);
    virtual ~ViewDelegate() override;
    virtual void drawInMTKView(MTK::View* view) override;

  private:
    Renderer* renderer;
};