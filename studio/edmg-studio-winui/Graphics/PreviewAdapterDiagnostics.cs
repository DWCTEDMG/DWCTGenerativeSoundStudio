using Vortice.DXGI;

namespace EdmgStudio.WinUI.Graphics;

public sealed record PreviewAdapterDiagnostics(
    string Description,
    uint VendorId,
    uint DeviceId,
    ulong DedicatedVideoMemory,
    ulong SharedSystemMemory,
    long Luid,
    bool IsWarp)
{
    internal static PreviewAdapterDiagnostics FromAdapter(IDXGIAdapter1 adapter, bool isWarp)
    {
        AdapterDescription1 description = adapter.Description1;
        return new(
            description.Description.TrimEnd('\0'),
            description.VendorId,
            description.DeviceId,
            description.DedicatedVideoMemory,
            description.SharedSystemMemory,
            description.Luid,
            isWarp);
    }

    public string LuidText => $"0x{unchecked((ulong)Luid):X16}";
}
