namespace EdmgStudio.Core.Graphics;

public readonly record struct PhysicalPixelSize(int Width, int Height)
{
    public bool IsRenderable => Width > 0 && Height > 0;
}

public enum PreviewDisplayMode
{
    Fit,
    Fill,
    ActualSize,
}

public readonly record struct PreviewRectangle(float X, float Y, float Width, float Height);

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

    public static PreviewRectangle CalculateAspectFit(
        int sourceWidth,
        int sourceHeight,
        int surfaceWidth,
        int surfaceHeight)
        => CalculatePresentation(sourceWidth, sourceHeight, surfaceWidth, surfaceHeight, PreviewDisplayMode.Fit);

    public static PreviewRectangle CalculatePresentation(
        int sourceWidth,
        int sourceHeight,
        int surfaceWidth,
        int surfaceHeight,
        PreviewDisplayMode displayMode)
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

        double widthScale = (double)surfaceWidth / sourceWidth;
        double heightScale = (double)surfaceHeight / sourceHeight;
        double scale = displayMode switch
        {
            PreviewDisplayMode.Fit => Math.Min(widthScale, heightScale),
            PreviewDisplayMode.Fill => Math.Max(widthScale, heightScale),
            PreviewDisplayMode.ActualSize => 1.0,
            _ => throw new ArgumentOutOfRangeException(nameof(displayMode)),
        };
        var width = (float)(sourceWidth * scale);
        var height = (float)(sourceHeight * scale);
        return new PreviewRectangle(
            (surfaceWidth - width) / 2.0f,
            (surfaceHeight - height) / 2.0f,
            width,
            height);
    }

    public static PreviewRectangle CalculateSafeArea(PreviewRectangle frame, double insetFraction)
    {
        if (!double.IsFinite(insetFraction) || insetFraction < 0 || insetFraction >= 0.5)
        {
            throw new ArgumentOutOfRangeException(nameof(insetFraction));
        }

        float horizontalInset = (float)(frame.Width * insetFraction);
        float verticalInset = (float)(frame.Height * insetFraction);
        return new PreviewRectangle(
            frame.X + horizontalInset,
            frame.Y + verticalInset,
            frame.Width - (2 * horizontalInset),
            frame.Height - (2 * verticalInset));
    }
}
