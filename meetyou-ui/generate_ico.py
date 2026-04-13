import os
from PIL import Image, ImageDraw, ImageFont

def generate_icons():
    size = 1024
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background: Premium dark gray #171717 with rounded corners
    bg_color = (23, 23, 23, 255)
    radius = 224
    draw.rounded_rectangle([(0, 0), (size, size)], radius=radius, fill=bg_color)

    # Draw the "M" logo
    # We'll use a very simple and thick polyline
    line_color = (245, 245, 245, 255)
    line_width = 80
    points = [
        (272, 752),
        (272, 432),
        (424, 272),
        (512, 368),
        (600, 272),
        (752, 432),
        (752, 752)
    ]
    draw.line(points, fill=line_color, width=line_width, joint="curve")

    # To make it look perfect, let's just save this generated image.
    os.makedirs('build', exist_ok=True)
    os.makedirs('public', exist_ok=True)
    
    img.save('public/icon.png', 'PNG')
    
    img_ico = img.resize((256, 256), Image.Resampling.LANCZOS)
    img_ico.save('build/icon.ico', format='ICO', sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
    print("Generated public/icon.png and build/icon.ico")

if __name__ == '__main__':
    generate_icons()
