namespace EdmgStudio.Core.Media;

internal interface IVideoDecoder
{
    Task<VideoMetadata> ProbeAsync(string sourcePath, CancellationToken cancellationToken = default);

    Task DecodeAsync(
        string sourcePath,
        VideoMetadata metadata,
        TimeSpan startPosition,
        Action<EdmgStudio.Core.Graphics.OwnedCpuFrame> submitFrame,
        bool paceFrames = true,
        int? maximumFrames = null,
        CancellationToken cancellationToken = default);
}
