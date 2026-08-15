using SharpGen.Runtime;
using Vortice.Direct3D;
using Vortice.Direct3D11;
using Vortice.DXGI;
using static Vortice.Direct3D11.D3D11;
using static Vortice.DXGI.DXGI;

namespace EdmgStudio.WinUI.Graphics;

internal sealed class D3D11DeviceResources : IDisposable
{
    public D3D11DeviceResources(
        IDXGIFactory6 factory,
        IDXGIAdapter1 adapter,
        ID3D11Device device,
        ID3D11DeviceContext context,
        PreviewAdapterDiagnostics diagnostics)
    {
        Factory = factory;
        Adapter = adapter;
        Device = device;
        Context = context;
        Diagnostics = diagnostics;
    }

    public IDXGIFactory6 Factory { get; }
    public IDXGIAdapter1 Adapter { get; }
    public ID3D11Device Device { get; }
    public ID3D11DeviceContext Context { get; }
    public PreviewAdapterDiagnostics Diagnostics { get; }

    public void Dispose()
    {
        List<Exception>? failures = null;
        try
        {
            Context.ClearState();
            Context.Flush();
        }
        catch (Exception exception)
        {
            AddFailure(ref failures, exception);
        }

        DisposeResource(Context, ref failures);
        DisposeResource(Device, ref failures);
        DisposeResource(Adapter, ref failures);
        DisposeResource(Factory, ref failures);

        if (failures is { Count: > 0 })
        {
            throw new AggregateException("One or more Direct3D device resources could not be released.", failures);
        }
    }

    private static void DisposeResource(IDisposable resource, ref List<Exception>? failures)
    {
        try
        {
            resource.Dispose();
        }
        catch (Exception exception)
        {
            AddFailure(ref failures, exception);
        }
    }

    private static void AddFailure(ref List<Exception>? failures, Exception exception)
    {
        failures ??= [];
        failures.Add(exception);
    }
}

internal static class D3D11DeviceFactory
{
    private static readonly FeatureLevel[] FeatureLevels =
    [
        FeatureLevel.Level_11_1,
        FeatureLevel.Level_11_0,
        FeatureLevel.Level_10_1,
        FeatureLevel.Level_10_0,
    ];

    public static D3D11DeviceResources Create(bool forceWarp = false)
    {
        IDXGIFactory6 factory = CreateDXGIFactory2<IDXGIFactory6>(false);
        if (!forceWarp)
        {
            for (uint index = 0; ; index++)
            {
                Result result = factory.EnumAdapterByGpuPreference(
                    index,
                    GpuPreference.HighPerformance,
                    out IDXGIAdapter1? adapter);
                if (result.Failure)
                {
                    break;
                }

                if (adapter is null)
                {
                    continue;
                }

                if ((adapter.Description1.Flags & AdapterFlags.Software) != 0)
                {
                    adapter.Dispose();
                    continue;
                }

                if (TryCreate(factory, adapter, DriverType.Unknown, isWarp: false, out D3D11DeviceResources? resources))
                {
                    return resources!;
                }

                adapter.Dispose();
            }
        }

        IDXGIAdapter1 warpAdapter = factory.EnumWarpAdapter<IDXGIAdapter1>();
        if (warpAdapter is null)
        {
            factory.Dispose();
            throw new InvalidOperationException("DXGI did not return a WARP adapter.");
        }
        if (TryCreate(factory, warpAdapter, DriverType.Unknown, isWarp: true, out D3D11DeviceResources? warpResources))
        {
            return warpResources!;
        }

        warpAdapter.Dispose();
        factory.Dispose();
        throw new InvalidOperationException("Direct3D 11 could not create a hardware or WARP preview device.");
    }

    private static bool TryCreate(
        IDXGIFactory6 factory,
        IDXGIAdapter1 adapter,
        DriverType driverType,
        bool isWarp,
        out D3D11DeviceResources? resources)
    {
        Result result = D3D11CreateDevice(
            adapter,
            driverType,
            DeviceCreationFlags.BgraSupport,
            FeatureLevels,
            out ID3D11Device? device,
            out _,
            out ID3D11DeviceContext? context);
        if (result.Failure || device is null || context is null)
        {
            device?.Dispose();
            context?.Dispose();
            resources = null;
            return false;
        }

        resources = new(factory, adapter, device, context, PreviewAdapterDiagnostics.FromAdapter(adapter, isWarp));
        return true;
    }
}
