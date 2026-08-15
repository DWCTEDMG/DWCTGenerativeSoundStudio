using EdmgStudio.Core.Graphics;
using Vortice.Direct3D11;
using Vortice.DXGI;

namespace EdmgStudio.WinUI.Graphics;

internal sealed class CpuFrameUploader : IFrameUploader
{
    private readonly ID3D11Device _device;
    private readonly ID3D11DeviceContext _context;
    private ID3D11Texture2D? _uploadTexture;
    private ID3D11Texture2D? _renderTexture;
    private int _width;
    private int _height;

    public CpuFrameUploader(ID3D11Device device, ID3D11DeviceContext context)
    {
        _device = device;
        _context = context;
    }

    public ID3D11Texture2D Upload(OwnedCpuFrame frame)
    {
        EnsureTextures(frame.Layout.Width, frame.Layout.Height);
        MappedSubresource mapped = _context.Map(
            _uploadTexture!,
            0,
            MapMode.WriteDiscard,
            Vortice.Direct3D11.MapFlags.None);
        try
        {
            if (mapped.RowPitch < frame.Layout.RowBytes)
            {
                throw new InvalidOperationException("The D3D11 upload row pitch is smaller than the validated frame row.");
            }

            Span<byte> destination = mapped.AsSpan(checked((int)mapped.RowPitch * frame.Layout.Height));
            int rowPitch = checked((int)mapped.RowPitch);
            for (int row = 0; row < frame.Layout.Height; row++)
            {
                frame.CopyRowToBgra(row, destination.Slice(row * rowPitch, rowPitch));
            }
        }
        finally
        {
            _context.Unmap(_uploadTexture!, 0);
        }

        _context.CopyResource(_renderTexture!, _uploadTexture!);
        return _renderTexture!;
    }

    public void Reset()
    {
        ID3D11Texture2D? renderTexture = _renderTexture;
        _renderTexture = null;
        ID3D11Texture2D? uploadTexture = _uploadTexture;
        _uploadTexture = null;
        _width = 0;
        _height = 0;

        Exception? renderFailure = null;
        try
        {
            renderTexture?.Dispose();
        }
        catch (Exception exception)
        {
            renderFailure = exception;
        }

        try
        {
            uploadTexture?.Dispose();
        }
        catch (Exception exception) when (renderFailure is not null)
        {
            throw new AggregateException(
                "The Direct3D preview upload textures could not be released.",
                renderFailure,
                exception);
        }

        if (renderFailure is not null)
        {
            throw renderFailure;
        }
    }

    public void Dispose() => Reset();

    private void EnsureTextures(int width, int height)
    {
        if (_uploadTexture is not null && width == _width && height == _height)
        {
            return;
        }

        Reset();
        Texture2DDescription uploadDescription = new(
            Format.B8G8R8A8_UNorm,
            (uint)width,
            (uint)height,
            1,
            1,
            BindFlags.None,
            ResourceUsage.Dynamic,
            CpuAccessFlags.Write,
            1,
            0,
            ResourceOptionFlags.None);
        Texture2DDescription renderDescription = new(
            Format.B8G8R8A8_UNorm,
            (uint)width,
            (uint)height,
            1,
            1,
            BindFlags.ShaderResource | BindFlags.RenderTarget,
            ResourceUsage.Default,
            CpuAccessFlags.None,
            1,
            0,
            ResourceOptionFlags.None);

        _uploadTexture = _device.CreateTexture2D(uploadDescription);
        _renderTexture = _device.CreateTexture2D(renderDescription);
        _width = width;
        _height = height;
    }
}
