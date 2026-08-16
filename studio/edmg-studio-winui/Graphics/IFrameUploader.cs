using EdmgStudio.Core.Graphics;
using Vortice.Direct3D11;

namespace EdmgStudio.WinUI.Graphics;

/// <summary>
/// Narrow upload boundary. A future CUDA shared-texture implementation can replace this
/// CPU uploader without changing the preview control, renderer session, or backend contract.
/// </summary>
internal interface IFrameUploader : IDisposable
{
    ID3D11Texture2D Upload(OwnedCpuFrame frame);
    void Reset();
}
