using System.Runtime.InteropServices;
using EdmgStudio.Core.Models;

namespace EdmgStudio.WinUI.Services;

public sealed class WindowsTaskbarProgressService : IDisposable
{
    private readonly nint _windowHandle;
    private ITaskbarList3? _taskbar;

    public WindowsTaskbarProgressService(nint windowHandle)
    {
        _windowHandle = windowHandle;
        try
        {
            Type taskbarType = Type.GetTypeFromCLSID(new Guid("56FDF344-FD6D-11D0-958A-006097C9A090"), throwOnError: true)!;
            _taskbar = (ITaskbarList3)Activator.CreateInstance(taskbarType)!;
            _taskbar.HrInit();
        }
        catch (Exception exception)
        {
            CrashLogger.Write("Windows taskbar progress is unavailable.", exception);
            _taskbar = null;
        }
    }

    public void Update(StudioTaskbarProgress progress)
    {
        if (_taskbar is null || _windowHandle == 0)
        {
            return;
        }

        try
        {
            _taskbar.SetProgressState(_windowHandle, MapState(progress.State));
            if (progress.State is StudioTaskbarProgressState.Normal or StudioTaskbarProgressState.Paused)
            {
                _taskbar.SetProgressValue(_windowHandle, (ulong)Math.Round(progress.Percent), 100);
            }
        }
        catch (Exception exception)
        {
            CrashLogger.Write("Unable to update Windows taskbar progress.", exception);
        }
    }

    public void Dispose()
    {
        Update(StudioTaskbarProgress.None);
        if (_taskbar is not null && Marshal.IsComObject(_taskbar))
        {
            Marshal.FinalReleaseComObject(_taskbar);
        }

        _taskbar = null;
    }

    private static TaskbarProgressState MapState(StudioTaskbarProgressState state) => state switch
    {
        StudioTaskbarProgressState.Indeterminate => TaskbarProgressState.Indeterminate,
        StudioTaskbarProgressState.Normal => TaskbarProgressState.Normal,
        StudioTaskbarProgressState.Error => TaskbarProgressState.Error,
        StudioTaskbarProgressState.Paused => TaskbarProgressState.Paused,
        _ => TaskbarProgressState.NoProgress,
    };

    private enum TaskbarProgressState : uint
    {
        NoProgress = 0,
        Indeterminate = 0x1,
        Normal = 0x2,
        Error = 0x4,
        Paused = 0x8,
    }

    [ComImport]
    [Guid("EA1AFB91-9E28-4B86-90E9-9E9F8A5EEA84")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface ITaskbarList3
    {
        void HrInit();
        void AddTab(nint window);
        void DeleteTab(nint window);
        void ActivateTab(nint window);
        void SetActiveAlt(nint window);
        void MarkFullscreenWindow(nint window, [MarshalAs(UnmanagedType.Bool)] bool fullscreen);
        void SetProgressValue(nint window, ulong completed, ulong total);
        void SetProgressState(nint window, TaskbarProgressState state);
    }
}
