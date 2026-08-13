using System.ComponentModel;
using System.Diagnostics;
using System.Net;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace EdmgStudio.Core.Services;

/// <summary>
/// Contains a managed backend and all descendants in a Windows Job Object.
/// Closing the owning client process closes the job handle, which terminates
/// any backend descendants that survived an abnormal client shutdown.
/// </summary>
internal sealed class WindowsProcessJob : IDisposable
{
    private const uint JobObjectLimitKillOnJobClose = 0x00002000;
    private const int JobObjectBasicProcessIdListClass = 3;
    private const int JobObjectExtendedLimitInformationClass = 9;
    private const int ErrorInsufficientBuffer = 122;
    private const int ErrorMoreData = 234;
    private const int AddressFamilyInet = 2;
    private const int TcpTableOwnerPidListener = 3;

    private readonly SafeFileHandle _handle;

    private WindowsProcessJob(SafeFileHandle handle)
    {
        _handle = handle;
    }

    public static WindowsProcessJob CreateKillOnClose()
    {
        if (!OperatingSystem.IsWindows())
        {
            throw new PlatformNotSupportedException("Windows Job Objects are available only on Windows.");
        }

        var handle = CreateJobObject(IntPtr.Zero, null);
        if (handle.IsInvalid)
        {
            throw new Win32Exception(Marshal.GetLastWin32Error(), "The backend containment job could not be created.");
        }

        var limits = new JobObjectExtendedLimitInformation
        {
            BasicLimitInformation = new JobObjectBasicLimitInformation
            {
                LimitFlags = JobObjectLimitKillOnJobClose
            }
        };

        if (!SetInformationJobObject(
                handle,
                JobObjectExtendedLimitInformationClass,
                ref limits,
                (uint)Marshal.SizeOf<JobObjectExtendedLimitInformation>()))
        {
            var error = new Win32Exception(
                Marshal.GetLastWin32Error(),
                "The backend containment job could not enable kill-on-close protection.");
            handle.Dispose();
            throw error;
        }

        return new WindowsProcessJob(handle);
    }

    public void Assign(Process process)
    {
        ArgumentNullException.ThrowIfNull(process);
        if (!AssignProcessToJobObject(_handle, process.SafeHandle))
        {
            throw new Win32Exception(
                Marshal.GetLastWin32Error(),
                "The managed backend could not be assigned to the containment job.");
        }
    }

    public bool OwnsTcpListener(int port)
    {
        if (port is < 1 or > 65535)
        {
            return false;
        }

        var processIds = GetAssignedProcessIds();
        return GetIpv4ListenerOwners(port).Any(processIds.Contains);
    }

    private HashSet<int> GetAssignedProcessIds()
    {
        for (var capacity = 32; capacity <= 4096; capacity *= 2)
        {
            var byteCount = checked(8 + (IntPtr.Size * capacity));
            var buffer = Marshal.AllocHGlobal(byteCount);
            try
            {
                if (!QueryInformationJobObject(
                        _handle,
                        JobObjectBasicProcessIdListClass,
                        buffer,
                        (uint)byteCount,
                        out _))
                {
                    var error = Marshal.GetLastWin32Error();
                    if (error == ErrorMoreData)
                    {
                        continue;
                    }

                    throw new Win32Exception(error, "The backend containment job could not be queried.");
                }

                var count = Marshal.ReadInt32(buffer, 4);
                var result = new HashSet<int>();
                for (var index = 0; index < count; index++)
                {
                    var offset = 8 + (index * IntPtr.Size);
                    var raw = IntPtr.Size == sizeof(long)
                        ? Marshal.ReadInt64(buffer, offset)
                        : Marshal.ReadInt32(buffer, offset);
                    if (raw is > 0 and <= int.MaxValue)
                    {
                        result.Add((int)raw);
                    }
                }

                return result;
            }
            finally
            {
                Marshal.FreeHGlobal(buffer);
            }
        }

        throw new InvalidOperationException("The backend containment job exceeded the supported process count.");
    }

    private static IEnumerable<int> GetIpv4ListenerOwners(int port)
    {
        var byteCount = 0;
        var status = GetExtendedTcpTable(
            IntPtr.Zero,
            ref byteCount,
            order: false,
            AddressFamilyInet,
            TcpTableOwnerPidListener,
            reserved: 0);
        if (status is not (0 or ErrorInsufficientBuffer) || byteCount <= 0)
        {
            yield break;
        }

        var buffer = Marshal.AllocHGlobal(byteCount);
        try
        {
            status = GetExtendedTcpTable(
                buffer,
                ref byteCount,
                order: false,
                AddressFamilyInet,
                TcpTableOwnerPidListener,
                reserved: 0);
            if (status != 0)
            {
                yield break;
            }

            var rowCount = Marshal.ReadInt32(buffer);
            var rowSize = Marshal.SizeOf<MibTcpRowOwnerPid>();
            var rowAddress = IntPtr.Add(buffer, sizeof(uint));
            for (var index = 0; index < rowCount; index++)
            {
                var row = Marshal.PtrToStructure<MibTcpRowOwnerPid>(IntPtr.Add(rowAddress, index * rowSize));
                var networkPort = unchecked((short)(row.LocalPort & 0xFFFF));
                var localPort = unchecked((ushort)IPAddress.NetworkToHostOrder(networkPort));
                if (localPort == port && row.OwningProcessId <= int.MaxValue)
                {
                    yield return (int)row.OwningProcessId;
                }
            }
        }
        finally
        {
            Marshal.FreeHGlobal(buffer);
        }
    }

    public void Dispose() => _handle.Dispose();

    [StructLayout(LayoutKind.Sequential)]
    private struct JobObjectBasicLimitInformation
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IoCounters
    {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JobObjectExtendedLimitInformation
    {
        public JobObjectBasicLimitInformation BasicLimitInformation;
        public IoCounters IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct MibTcpRowOwnerPid
    {
        public uint State;
        public uint LocalAddress;
        public uint LocalPort;
        public uint RemoteAddress;
        public uint RemotePort;
        public uint OwningProcessId;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateJobObject(IntPtr jobAttributes, string? name);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetInformationJobObject(
        SafeFileHandle job,
        int informationClass,
        ref JobObjectExtendedLimitInformation information,
        uint informationLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool AssignProcessToJobObject(SafeFileHandle job, SafeProcessHandle process);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool QueryInformationJobObject(
        SafeFileHandle job,
        int informationClass,
        IntPtr information,
        uint informationLength,
        out uint returnLength);

    [DllImport("iphlpapi.dll", SetLastError = true)]
    private static extern int GetExtendedTcpTable(
        IntPtr table,
        ref int byteCount,
        [MarshalAs(UnmanagedType.Bool)] bool order,
        int addressFamily,
        int tableClass,
        int reserved);
}
