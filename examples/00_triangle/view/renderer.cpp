#include "renderer.h"
#include "mesh_factory.h"

#include <stdexcept>

Renderer::Renderer(MTL::Device* device) : device(device->retain()) {
    commandQueue = device->newCommandQueue();
    buildMeshes();
    buildShaders();
}

Renderer::~Renderer() {
    triangleMesh->release();
    trianglePipeline->release();
    generalPipeline->release();
    commandQueue->release();
    device->release();
}

void Renderer::buildMeshes() {
    triangleMesh = MeshFactory::build_triangle(device);
}

void Renderer::buildShaders() {
    const std::string shaderDirectory = AETHER_TUTORIAL_SHADER_DIR;
    trianglePipeline =
        buildShader((shaderDirectory + "/triangle.metal").c_str(), "vertexMain", "fragmentMain");
    generalPipeline = buildShader((shaderDirectory + "/general_shader.metal").c_str(),
                                  "vertexMainGeneral", "fragmentMainGeneral");
}

MTL::RenderPipelineState* Renderer::buildShader(const char* filename, const char* vertName,
                                                const char* fragName) {

    // Read the source code from the file.
    std::ifstream file;
    file.open(filename);
    if (!file) {
        throw std::runtime_error(std::string("Unable to open tutorial shader: ") + filename);
    }
    std::stringstream reader;
    reader << file.rdbuf();
    std::string raw_string = reader.str();
    NS::String* source_code =
        NS::String::string(raw_string.c_str(), NS::StringEncoding::UTF8StringEncoding);

    // A Metal Library constructs functions from source code
    NS::Error* error = nullptr;
    MTL::CompileOptions* options = nullptr;
    MTL::Library* library = device->newLibrary(source_code, options, &error);
    if (!library) {
        const std::string message = error ? error->localizedDescription()->utf8String()
                                          : "Unknown Metal shader compilation error";
        throw std::runtime_error(message);
    }

    NS::String* vertexName = NS::String::string(vertName, NS::StringEncoding::UTF8StringEncoding);
    MTL::Function* vertexMain = library->newFunction(vertexName);

    NS::String* fragmentName = NS::String::string(fragName, NS::StringEncoding::UTF8StringEncoding);
    MTL::Function* fragmentMain = library->newFunction(fragmentName);

    MTL::RenderPipelineDescriptor* pipelineDescriptor =
        MTL::RenderPipelineDescriptor::alloc()->init();
    pipelineDescriptor->setVertexFunction(vertexMain);
    pipelineDescriptor->setFragmentFunction(fragmentMain);
    pipelineDescriptor->colorAttachments()->object(0)->setPixelFormat(
        MTL::PixelFormat::PixelFormatBGRA8Unorm_sRGB);

    MTL::RenderPipelineState* pipeline = device->newRenderPipelineState(pipelineDescriptor, &error);
    if (!pipeline) {
        const std::string message = error ? error->localizedDescription()->utf8String()
                                          : "Unknown Metal pipeline creation error";
        vertexMain->release();
        fragmentMain->release();
        pipelineDescriptor->release();
        library->release();
        throw std::runtime_error(message);
    }

    vertexMain->release();
    fragmentMain->release();
    pipelineDescriptor->release();
    library->release();
    file.close();

    return pipeline;
}

void Renderer::draw(MTK::View* view) {

    NS::AutoreleasePool* pool = NS::AutoreleasePool::alloc()->init();

    MTL::CommandBuffer* commandBuffer = commandQueue->commandBuffer();
    MTL::RenderPassDescriptor* renderPass = view->currentRenderPassDescriptor();
    CA::MetalDrawable* drawable = view->currentDrawable();
    if (!commandBuffer || !renderPass || !drawable) {
        pool->release();
        return;
    }
    MTL::RenderCommandEncoder* encoder = commandBuffer->renderCommandEncoder(renderPass);
    if (!encoder) {
        pool->release();
        return;
    }

    encoder->setRenderPipelineState(generalPipeline);
    // buffer, offset, index
    encoder->setVertexBuffer(triangleMesh, 0, 0);
    encoder->drawPrimitives(MTL::PrimitiveType::PrimitiveTypeTriangle, NS::UInteger(0),
                            NS::UInteger(3));

    encoder->endEncoding();
    commandBuffer->presentDrawable(drawable);
    commandBuffer->commit();

    pool->release();
}
