using System.Buffers;
using EdmgStudio.Core.Graphics;
using Windows.Graphics.Imaging;

namespace EdmgStudio.WinUI.Graphics;

internal sealed class PreviewUnsupportedException : NotSupportedException
{
    public PreviewUnsupportedException(string message)
        : base(message)
    {
    }

    public PreviewUnsupportedException(string message, Exception innerException)
        : base(message, innerException)
    {
    }
}

/// <summary>
/// Decodes a callback-scoped image stream into one owned premultiplied BGRA8 frame.
/// Non-seekable HTTP streams are bounded and spooled to a delete-on-close file so the
/// preview path never retains a second whole compressed-media byte array.
/// </summary>
internal sealed class ImageFrameDecoder
{
    internal const long MaxCompressedBytes = 256L * 1024 * 1024;

    private static readonly HashSet<string> SupportedContentTypes = new(StringComparer.OrdinalIgnoreCase)
    {
        "image/bmp",
        "image/gif",
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/tiff",
        "image/vnd.microsoft.icon",
        "image/webp",
        "image/x-icon",
    };

    public static bool SupportsContentType(string? contentType) =>
        contentType is null ||
        contentType.Length == 0 ||
        contentType.Equals("application/octet-stream", StringComparison.OrdinalIgnoreCase) ||
        SupportedContentTypes.Contains(contentType.Split(';', 2)[0].Trim());

    public async Task<OwnedCpuFrame> DecodeAsync(
        Stream source,
        string? contentType,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(source);
        if (!SupportsContentType(contentType))
        {
            throw new PreviewUnsupportedException(
                contentType?.StartsWith("video/", StringComparison.OrdinalIgnoreCase) == true
                    ? "Video preview is not available in this build."
                    : $"Preview does not support media type '{contentType}'.");
        }

        Stream? spool = null;
        try
        {
            Stream decodeStream = source;
            if (!source.CanSeek)
            {
                spool = CreateDeleteOnCloseSpool();
                await CopyBoundedAsync(source, spool, cancellationToken).ConfigureAwait(false);
                spool.Position = 0;
                decodeStream = spool;
            }
            else
            {
                long remaining = checked(source.Length - source.Position);
                if (remaining < 0 || remaining > MaxCompressedBytes)
                {
                    throw new InvalidDataException(
                        $"Compressed preview exceeds the {MaxCompressedBytes / (1024 * 1024)} MiB limit.");
                }
            }

            using Windows.Storage.Streams.IRandomAccessStream randomAccessStream =
                decodeStream.AsRandomAccessStream();
            BitmapDecoder decoder = await BitmapDecoder.CreateAsync(randomAccessStream)
                .AsTask(cancellationToken)
                .ConfigureAwait(false);

            uint width = decoder.OrientedPixelWidth;
            uint height = decoder.OrientedPixelHeight;
            ValidateDecodedDimensions(width, height);

            PixelDataProvider pixels = await decoder.GetPixelDataAsync(
                    BitmapPixelFormat.Bgra8,
                    BitmapAlphaMode.Premultiplied,
                    new BitmapTransform(),
                    ExifOrientationMode.RespectExifOrientation,
                    ColorManagementMode.ColorManageToSRgb)
                .AsTask(cancellationToken)
                .ConfigureAwait(false);

            byte[] data = pixels.DetachPixelData();
            var owner = new ByteArrayMemoryOwner(data);
            return OwnedCpuFrame.Create(
                owner,
                data.Length,
                checked((int)width),
                checked((int)height),
                checked((int)width * FrameLayout.BytesPerPixel),
                FramePixelFormat.Bgra8,
                FrameOrientation.TopDown,
                TimeSpan.Zero);
        }
        catch (ArgumentException exception)
        {
            throw new PreviewUnsupportedException("The selected artifact is not a supported image.", exception);
        }
        finally
        {
            if (spool is not null)
            {
                await spool.DisposeAsync().ConfigureAwait(false);
            }
        }
    }

    private static FileStream CreateDeleteOnCloseSpool()
    {
        string path = Path.Combine(Path.GetTempPath(), $"edmg-preview-{Guid.NewGuid():N}.tmp");
        return new FileStream(
            path,
            FileMode.CreateNew,
            FileAccess.ReadWrite,
            FileShare.Read,
            bufferSize: 64 * 1024,
            FileOptions.Asynchronous | FileOptions.SequentialScan | FileOptions.DeleteOnClose);
    }

    private static async Task CopyBoundedAsync(
        Stream source,
        Stream destination,
        CancellationToken cancellationToken)
    {
        byte[] buffer = ArrayPool<byte>.Shared.Rent(64 * 1024);
        long copied = 0;
        try
        {
            while (true)
            {
                int read = await source.ReadAsync(buffer.AsMemory(0, buffer.Length), cancellationToken)
                    .ConfigureAwait(false);
                if (read == 0)
                {
                    break;
                }

                copied = checked(copied + read);
                if (copied > MaxCompressedBytes)
                {
                    throw new InvalidDataException(
                        $"Compressed preview exceeds the {MaxCompressedBytes / (1024 * 1024)} MiB limit.");
                }

                await destination.WriteAsync(buffer.AsMemory(0, read), cancellationToken)
                    .ConfigureAwait(false);
            }

            await destination.FlushAsync(cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            ArrayPool<byte>.Shared.Return(buffer);
        }
    }

    private static void ValidateDecodedDimensions(uint width, uint height)
    {
        if (width == 0 || height == 0 ||
            width > FrameLayout.MaximumDimension ||
            height > FrameLayout.MaximumDimension)
        {
            throw new InvalidDataException(
                $"Decoded image dimensions {width}×{height} are outside the supported range.");
        }

        long decodedBytes = checked((long)width * height * FrameLayout.BytesPerPixel);
        if (decodedBytes > FrameLayout.MaximumDecodedBytes)
        {
            throw new InvalidDataException(
                $"Decoded image exceeds the {FrameLayout.MaximumDecodedBytes / (1024 * 1024)} MiB limit.");
        }
    }

    private sealed class ByteArrayMemoryOwner : IMemoryOwner<byte>
    {
        private byte[]? _data;

        public ByteArrayMemoryOwner(byte[] data)
        {
            _data = data;
        }

        public Memory<byte> Memory =>
            _data is { } data
                ? data
                : throw new ObjectDisposedException(nameof(ByteArrayMemoryOwner));

        public void Dispose() => _data = null;
    }
}
