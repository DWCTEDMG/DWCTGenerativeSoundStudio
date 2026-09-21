using System.Runtime.InteropServices;

namespace EdmgStudio.WinUI.Services;

internal static class WindowsPackageIdentity
{
    private const int ErrorSuccess = 0;
    private const int ErrorInsufficientBuffer = 122;

    public static bool IsPackaged { get; } = DetectPackageIdentity();

    private static bool DetectPackageIdentity()
    {
        uint packageFullNameLength = 0;
        int result = GetCurrentPackageFullName(ref packageFullNameLength, null);
        return result is ErrorSuccess or ErrorInsufficientBuffer;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetCurrentPackageFullName(
        ref uint packageFullNameLength,
        char[]? packageFullName);
}
