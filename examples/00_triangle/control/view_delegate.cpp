//
// Created by Swayam Singal on 10/05/26.
//

#include "view_delegate.h"

ViewDelegate::ViewDelegate(MTL::Device* device)
    : MTK::ViewDelegate(), renderer(new Renderer(device)) {}

ViewDelegate::~ViewDelegate() {
    delete renderer;
}

void ViewDelegate::drawInMTKView(MTK::View* view) {
    renderer->draw(view);
}