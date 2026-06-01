# SedGo AI SEO Assets

This directory should contain:

1. **favicon.png** (32x32 or 64x64) - Website favicon
2. **apple-touch-icon.png** (180x180) - iOS home screen icon
3. **og-image.png** (1200x630) - Open Graph share image

## Requirements

### Favicon (favicon.png)
- Size: 32x32 pixels (recommended: also provide 16x16, 48x48)
- Format: PNG with alpha transparency
- Location: Root of static folder

### Apple Touch Icon (apple-touch-icon.png)
- Size: 180x180 pixels
- Format: PNG
- Location: Root of static folder

### Open Graph Image (og-image.png)
- Size: 1200x630 pixels (recommended)
- Format: PNG or JPG
- Location: Root of static folder
- Should include your brand logo and a clear message

## Usage

After adding these files, update your HTML head section:

```html
<link rel="icon" type="image/png" href="/static/favicon.png" />
<link rel="apple-touch-icon" sizes="180x180" href="/static/apple-touch-icon.png" />
```

And in Open Graph meta tags:

```html
<meta property="og:image" content="https://sedgo.ai/static/og-image.png" />
<meta property="og:image:width" content="1200" />
<meta property="og:image:height" content="630" />
```
