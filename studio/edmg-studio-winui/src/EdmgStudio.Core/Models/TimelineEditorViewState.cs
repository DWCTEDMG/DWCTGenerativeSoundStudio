namespace EdmgStudio.Core.Models;

/// <summary>Project-specific, non-destructive timeline view state.</summary>
public sealed record TimelineEditorViewState(
    double PositionSeconds,
    double PixelsPerSecond,
    double HorizontalOffset,
    double VerticalOffset,
    string? SelectedLaneId)
{
    public TimelineEditorViewState Normalize(
        double durationSeconds,
        double minimumPixelsPerSecond,
        double maximumPixelsPerSecond,
        double viewportWidth,
        double contentHeight,
        double viewportHeight,
        IEnumerable<string> laneIds)
    {
        double duration = double.IsFinite(durationSeconds) ? Math.Max(0, durationSeconds) : 0;
        double minimumZoom = double.IsFinite(minimumPixelsPerSecond) && minimumPixelsPerSecond > 0
            ? minimumPixelsPerSecond
            : 1;
        double maximumZoom = double.IsFinite(maximumPixelsPerSecond) && maximumPixelsPerSecond >= minimumZoom
            ? maximumPixelsPerSecond
            : minimumZoom;
        double pixelsPerSecond = double.IsFinite(PixelsPerSecond)
            ? Math.Clamp(PixelsPerSecond, minimumZoom, maximumZoom)
            : minimumZoom;
        double width = double.IsFinite(viewportWidth) ? Math.Max(0, viewportWidth) : 0;
        double height = double.IsFinite(viewportHeight) ? Math.Max(0, viewportHeight) : 0;
        double maximumHorizontalOffset = Math.Max(0, (duration * pixelsPerSecond) - width);
        double maximumVerticalOffset = Math.Max(0,
            (double.IsFinite(contentHeight) ? Math.Max(0, contentHeight) : 0) - height);
        HashSet<string> availableLaneIds = laneIds
            .Where(id => !string.IsNullOrWhiteSpace(id))
            .ToHashSet(StringComparer.Ordinal);

        return this with
        {
            PositionSeconds = Math.Clamp(
                double.IsFinite(PositionSeconds) ? PositionSeconds : 0,
                0,
                duration),
            PixelsPerSecond = pixelsPerSecond,
            HorizontalOffset = Math.Clamp(
                double.IsFinite(HorizontalOffset) ? HorizontalOffset : 0,
                0,
                maximumHorizontalOffset),
            VerticalOffset = Math.Clamp(
                double.IsFinite(VerticalOffset) ? VerticalOffset : 0,
                0,
                maximumVerticalOffset),
            SelectedLaneId = SelectedLaneId is not null && availableLaneIds.Contains(SelectedLaneId)
                ? SelectedLaneId
                : null,
        };
    }
}
