namespace EdmgStudio.Core.Graphics;

public readonly record struct PhysicalPixelSize(int Width, int Height)
{
    public bool IsRenderable => Width > 0 && Height > 0;
}

public readonly record struct AspectFitRectangle(float X, float Y, float Width, float Height);

public static class PreviewGeometry
{
    public static PhysicalPixelSize ToPhysicalPixels(double widthInDips, double heightInDips, double rasterizationScale)
    {
        if (!double.IsFinite(widthInDips) || widthInDips < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(widthInDips));
        }

        if (!double.IsFinite(heightInDips) || heightInDips < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(heightInDips));
        }

        if (!double.IsFinite(rasterizationScale) || rasterizationScale <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(rasterizationScale));
        }

        if (widthInDips == 0 || heightInDips == 0)
        {
            return default;
        }

        var physicalWidth = checked((int)Math.Ceiling(widthInDips * rasterizationScale));
        var physicalHeight = checked((int)Math.Ceiling(heightInDips * rasterizationScale));
        return new PhysicalPixelSize(Math.Max(1, physicalWidth), Math.Max(1, physicalHeight));
    }

    public static AspectFitRectangle CalculateAspectFit(
        int sourceWidth,
        int sourceHeight,
        int surfaceWidth,
        int surfaceHeight)
    {
        if (sourceWidth <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(sourceWidth));
        }

        if (sourceHeight <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(sourceHeight));
        }

        if (surfaceWidth <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(surfaceWidth));
        }

        if (surfaceHeight <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(surfaceHeight));
        }

        var scale = Math.Min((double)surfaceWidth / sourceWidth, (double)surfaceHeight / sourceHeight);
        var fittedWidth = (float)(sourceWidth * scale);
        var fittedHeight = (float)(sourceHeight * scale);
        return new AspectFitRectangle(
            (surfaceWidth - fittedWidth) / 2.0f,
            (surfaceHeight - fittedHeight) / 2.0f,
            fittedWidth,
            fittedHeight);
    }
}
