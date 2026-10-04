import os
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

def generate_perfect_sfm_dataset():
    np.random.seed(42)
    
    # Generate 400 random 3D points
    num_points = 400
    points_3d = np.random.uniform(-160, 160, (num_points, 3))
    
    # Assign unique colors and sizes to each 3D point
    point_colors = np.random.randint(50, 255, (num_points, 3))
    point_sizes = np.random.uniform(8.0, 20.0, num_points)
    
    os.makedirs('toy-dataset/images', exist_ok=True)
    
    # We render at 1024x1024 (2x supersampling) and downsample to 512x512
    render_w, render_h = 1024, 1024
    width, height = 512, 512
    f = 800.0 # scale focal length for 1024x1024
    cx, cy = 512.0, 512.0
    
    # 5 views with a smaller camera rotation (0.12 radians ~ 7 degrees) to ensure high overlap
    for view_idx in range(5):
        angle = (view_idx - 2) * 0.12
        
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        R = np.array([
            [cos_a, 0, sin_a],
            [0,     1, 0],
            [-sin_a, 0, cos_a]
        ])
        
        t = np.array([0, 0, 500])
        
        # Initialize high-res image with high-frequency noise
        noise_data = np.random.randint(100, 160, (render_h, render_w, 3), dtype=np.uint8)
        img = Image.fromarray(noise_data, 'RGB')
        draw = ImageDraw.Draw(img)
        
        # Project and sort
        depths = []
        projected = []
        for pt_idx, pt in enumerate(points_3d):
            pt_cam = R.dot(pt) + t
            depths.append(pt_cam[2])
            projected.append(pt_cam)
            
        indices = np.argsort(depths)[::-1]
        
        for pt_idx in indices:
            pt_cam = projected[pt_idx]
            z = pt_cam[2]
            if z <= 10:
                continue
                
            x_img = f * pt_cam[0] / z + cx
            y_img = f * pt_cam[1] / z + cy
            
            # Scale radius with depth (high-res size)
            r_feat = (point_sizes[pt_idx] * f) / z
            
            if 0 < x_img < render_w and 0 < y_img < render_h:
                color1 = tuple(point_colors[pt_idx])
                color2 = (255 - color1[0], 255 - color1[1], 255 - color1[2])
                
                # Draw concentric circles
                draw.ellipse([x_img - r_feat, y_img - r_feat, x_img + r_feat, y_img + r_feat], fill=color1)
                draw.ellipse([x_img - r_feat/2, y_img - r_feat/2, x_img + r_feat/2, y_img + r_feat/2], fill=color2)
                # Draw crosshairs
                draw.line([x_img - r_feat, y_img, x_img + r_feat, y_img], fill=(255, 255, 255), width=2)
                draw.line([x_img, y_img - r_feat, x_img, y_img + r_feat], fill=(255, 255, 255), width=2)

        # Downsample to 512x512 using LANCZOS to get perfect anti-aliasing
        img = img.resize((width, height), Image.Resampling.LANCZOS)
        
        # Apply a mild Gaussian Blur to remove any remaining high-frequency aliasing
        img = img.filter(ImageFilter.GaussianBlur(1.0))
        
        # Save image
        img.save(f'toy-dataset/images/image_{view_idx+1:03d}.jpg', 'JPEG', quality=95)

if __name__ == '__main__':
    generate_perfect_sfm_dataset()
    print("Generated 5 anti-aliased SfM views in toy-dataset/images/")
