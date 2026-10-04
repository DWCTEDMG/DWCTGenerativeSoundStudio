using System.Buffers;

namespace EdmgStudio.Core.Graphics;

public sealed class OwnedCpuFrame : IDisposable
{
  private IMemoryOwner<byte>? _owner;
  private readonly int _sourceLength;

  private OwnedCpuFrame(
      IMemoryOwner<byte> owner,
      int sourceLength,
      FrameLayout layout,
      FramePixelFormat pixelFormat,
      FrameOrientation orientation,
      TimeSpan timestamp)
  {
    _owner = owner;
    _sourceLength = sourceLength;
    Layout = layout;
    PixelFormat = pixelFormat;
    Orientation = orientation;
    Timestamp = timestamp;
  }

  public FrameLayout Layout { get; }

  public FramePixelFormat PixelFormat { get; }

  public FrameOrientation Orientation { get; }

  public TimeSpan Timestamp { get; }

  public bool IsDisposed => _owner is null;

  public ReadOnlyMemory<byte> Data
  {
    get
    {
      IMemoryOwner<byte> owner = _owner ?? throw new ObjectDisposedException(nameof(OwnedCpuFrame));
      return owner.Memory[.._sourceLength];
    }
  }

  public static OwnedCpuFrame Create(
      IMemoryOwner<byte> owner,
      int sourceLength,
      int width,
      int height,
      int stride,
      FramePixelFormat pixelFormat,
      FrameOrientation orientation = FrameOrientation.TopDown,
      TimeSpan timestamp = default)
  {
    ArgumentNullException.ThrowIfNull(owner);

    try
    {
      if (!Enum.IsDefined(pixelFormat))
      {
        throw new ArgumentOutOfRangeException(nameof(pixelFormat));
      }

      if (!Enum.IsDefined(orientation))
      {
        throw new ArgumentOutOfRangeException(nameof(orientation));
      }

      if (sourceLength > owner.Memory.Length)
      {
        throw new ArgumentException(
            "The declared source length exceeds the owned memory length.",
            nameof(sourceLength));
      }

      FrameLayout layout = FrameLayout.Validate(width, height, stride, sourceLength);
      return new OwnedCpuFrame(owner, sourceLength, layout, pixelFormat, orientation, timestamp);
    }
    catch
    {
      owner.Dispose();
      throw;
    }
  }

  public void CopyToBgra(Span<byte> destination)
  {
    if (destination.Length < Layout.TightBufferLength)
    {
      throw new ArgumentException(
          $"Destination contains {destination.Length} bytes but {Layout.TightBufferLength} are required.",
          nameof(destination));
    }

    _ = Data.Span;
    for (int destinationRowIndex = 0; destinationRowIndex < Layout.Height; destinationRowIndex++)
    {
      Span<byte> destinationRow = destination.Slice(destinationRowIndex * Layout.RowBytes, Layout.RowBytes);
      CopyRowToBgra(destinationRowIndex, destinationRow);
    }
  }

  public void CopyRowToBgra(int destinationRowIndex, Span<byte> destination)
  {
    if ((uint)destinationRowIndex >= (uint)Layout.Height)
    {
      throw new ArgumentOutOfRangeException(nameof(destinationRowIndex));
    }

    if (destination.Length < Layout.RowBytes)
    {
      throw new ArgumentException(
          $"Destination row contains {destination.Length} bytes but {Layout.RowBytes} are required.",
          nameof(destination));
    }

    int sourceRowIndex = Orientation == FrameOrientation.TopDown
        ? destinationRowIndex
        : Layout.Height - destinationRowIndex - 1;
    ReadOnlySpan<byte> sourceRow = Data.Span.Slice(sourceRowIndex * Layout.Stride, Layout.RowBytes);
    Span<byte> destinationRow = destination[..Layout.RowBytes];

    if (PixelFormat == FramePixelFormat.Bgra8)
    {
      sourceRow.CopyTo(destinationRow);
      return;
    }

    for (int offset = 0; offset < Layout.RowBytes; offset += FrameLayout.BytesPerPixel)
    {
      destinationRow[offset] = sourceRow[offset + 2];
      destinationRow[offset + 1] = sourceRow[offset + 1];
      destinationRow[offset + 2] = sourceRow[offset];
      destinationRow[offset + 3] = sourceRow[offset + 3];
    }
  }

  public void Dispose()
  {
    Interlocked.Exchange(ref _owner, null)?.Dispose();
  }
}
