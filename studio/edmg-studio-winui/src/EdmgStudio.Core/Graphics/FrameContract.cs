namespace EdmgStudio.Core.Graphics;

public enum FramePixelFormat
{
    Bgra8,
    Rgba8
}

public enum FrameOrientation
{
    TopDown,
    BottomUp
}

public readonly record struct FrameLayout(
    int Width,
    int Height,
    int Stride,
    int RowBytes,
    int MinimumSourceLength,
    int TightBufferLength)
{
    public const int BytesPerPixel = 4;
    public const int MaximumDimension = 16_384;
    public const int MaximumDecodedBytes = 512 * 1024 * 1024;

    public static FrameLayout Validate(int width, int height, int stride, int sourceLength)
    {
        if (width <= 0 || width > MaximumDimension)
        {
            throw new ArgumentOutOfRangeException(
                nameof(width),
                width,
                $"Frame width must be between 1 and {MaximumDimension} pixels.");
        }

        if (height <= 0 || height > MaximumDimension)
        {
            throw new ArgumentOutOfRangeException(
                nameof(height),
                height,
                $"Frame height must be between 1 and {MaximumDimension} pixels.");
        }

        if (sourceLength < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(sourceLength));
        }

        int rowBytes;
        int tightBufferLength;
        try
        {
            rowBytes = checked(width * BytesPerPixel);
            tightBufferLength = checked(rowBytes * height);
        }
        catch (OverflowException exception)
        {
            throw new ArgumentException("Frame dimensions overflow the supported buffer range.", exception);
        }

        if (stride <= 0 || stride < rowBytes)
        {
            throw new ArgumentOutOfRangeException(
                nameof(stride),
                stride,
                $"Frame stride must be at least {rowBytes} bytes.");
        }

        if (tightBufferLength > MaximumDecodedBytes)
        {
            throw new ArgumentException(
                $"Decoded frames cannot exceed {MaximumDecodedBytes} bytes.",
                nameof(sourceLength));
        }

        int minimumSourceLength;
        try
        {
            minimumSourceLength = checked(((height - 1) * stride) + rowBytes);
        }
        catch (OverflowException exception)
        {
            throw new ArgumentException("Frame stride and height overflow the supported buffer range.", exception);
        }

        if (minimumSourceLength > MaximumDecodedBytes)
        {
            throw new ArgumentException(
                $"Decoded frames cannot exceed {MaximumDecodedBytes} bytes.",
                nameof(sourceLength));
        }

        if (sourceLength < minimumSourceLength)
        {
            throw new ArgumentException(
                $"Frame source contains {sourceLength} bytes but at least {minimumSourceLength} are required.",
                nameof(sourceLength));
        }

        return new FrameLayout(width, height, stride, rowBytes, minimumSourceLength, tightBufferLength);
    }
}
