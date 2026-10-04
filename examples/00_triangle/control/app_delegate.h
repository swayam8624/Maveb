//
// Created by Swayam Singal on 10/05/26.
//

#pragma once
#include "../config.h"
#include "view_delegate.h"

class AppDelegate : public NS::ApplicationDelegate {
  public:
    ~AppDelegate();

    virtual void applicationWillFinishLaunching(NS::Notification* notification) override;
    virtual void applicationDidFinishLaunching(NS::Notification* notification) override;
    virtual bool applicationShouldTerminateAfterLastWindowClosed(NS::Application* sender) override;

  private:
    NS::Window* window;
    MTK::View* mtkView;
    MTL::Device* device;
    ViewDelegate* viewDelegate = nullptr;
};