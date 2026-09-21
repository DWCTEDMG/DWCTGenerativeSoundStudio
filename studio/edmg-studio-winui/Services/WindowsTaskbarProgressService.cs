using System.Runtime.InteropServices;
using EdmgStudio.Core.Models;

namespace EdmgStudio.WinUI.Services;

public sealed class WindowsTaskbarProgressService : IDisposable
{
    private const uint ClsctxInprocServer = 0x1;
    private static readonly Guid TaskbarListClassId = new("56FDF344-FD6D-11D0-958A-006097C9A090");
    private static readonly Guid TaskbarList3InterfaceId = new("EA1AFB91-9E28-4B86-90E9-9E9F8A5EEA84");
    private readonly nint _windowHandle;
    private ITaskbarList3? _taskbar;

    public WindowsTaskbarProgressService(nint windowHandle)
    {
        _windowHandle = windowHandle;
        nint taskbarPointer = 0;
        try
        {
            int result = CoCreateInstance(
                TaskbarListClassId,
                0,
                ClsctxInprocServer,
                TaskbarList3InterfaceId,
                out taskbarPointer);
            if (result < 0 || taskbarPointer == 0)
            {
                return;
            }

            _taskbar = (ITaskbarList3)Marshal.GetObjectForIUnknown(taskbarPointer);
            if (_taskbar.HrInit() < 0)
            {
                ReleaseTaskbar();
            }
        }
        catch (Exception exception)
        {
            CrashLogger.Write("Windows taskbar progress is unavailable.", exception);
            ReleaseTaskbar();
        }
        finally
        {
            if (taskbarPointer != 0)
            {
                Marshal.Release(taskbarPointer);
            }
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
            int result = _taskbar.SetProgressState(_windowHandle, MapState(progress.State));
            if (progress.State is StudioTaskbarProgressState.Normal or StudioTaskbarProgressState.Paused)
            {
                result = _taskbar.SetProgressValue(_windowHandle, (ulong)Math.Round(progress.Percent), 100);
            }

            if (result < 0)
            {
                ReleaseTaskbar();
            }
        }
        catch (Exception exception)
        {
            CrashLogger.Write("Unable to update Windows taskbar progress.", exception);
            ReleaseTaskbar();
        }
    }

    public void Dispose()
    {
        Update(StudioTaskbarProgress.None);
        ReleaseTaskbar();
    }

    private void ReleaseTaskbar()
    {
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
        [PreserveSig] int HrInit();
        [PreserveSig] int AddTab(nint window);
        [PreserveSig] int DeleteTab(nint window);
        [PreserveSig] int ActivateTab(nint window);
        [PreserveSig] int SetActiveAlt(nint window);
        [PreserveSig] int MarkFullscreenWindow(nint window, [MarshalAs(UnmanagedType.Bool)] bool fullscreen);
        [PreserveSig] int SetProgressValue(nint window, ulong completed, ulong total);
        [PreserveSig] int SetProgressState(nint window, TaskbarProgressState state);
    }

    [DllImport("ole32.dll")]
    private static extern int CoCreateInstance(
        in Guid classId,
        nint outer,
        uint context,
        in Guid interfaceId,
        out nint instance);
}
