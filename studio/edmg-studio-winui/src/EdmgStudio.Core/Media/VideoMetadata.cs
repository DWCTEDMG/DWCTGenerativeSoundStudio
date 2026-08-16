using System.Globalization;
using System.Text.Json;

namespace EdmgStudio.Core.Media;

public sealed record VideoMetadata(
    int Width,
    int Height,
    TimeSpan Duration,
    double FramesPerSecond,
    int RotationDegrees)
{
    public const double DefaultFramesPerSecond = 30;

    public static VideoMetadata ParseFfprobeJson(string json)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(json);

        using JsonDocument document = JsonDocument.Parse(json);
        JsonElement root = document.RootElement;
        JsonElement videoStream = root.GetProperty("streams")
            .EnumerateArray()
            .FirstOrDefault(stream =>
                stream.TryGetProperty("codec_type", out JsonElement codecType)
                && string.Equals(codecType.GetString(), "video", StringComparison.OrdinalIgnoreCase));

        if (videoStream.ValueKind == JsonValueKind.Undefined)
        {
            throw new InvalidDataException("FFprobe did not report a video stream.");
        }

        int encodedWidth = ReadPositiveInt(videoStream, "width");
        int encodedHeight = ReadPositiveInt(videoStream, "height");
        int rotation = NormalizeRotation(ReadRotation(videoStream));
        bool swapsDimensions = rotation is 90 or 270;
        int width = swapsDimensions ? encodedHeight : encodedWidth;
        int height = swapsDimensions ? encodedWidth : encodedHeight;
        double framesPerSecond = ReadFrameRate(videoStream);
        TimeSpan duration = ReadDuration(videoStream, root);

        return new VideoMetadata(width, height, duration, framesPerSecond, rotation);
    }

    private static int ReadPositiveInt(JsonElement element, string propertyName)
    {
        if (!element.TryGetProperty(propertyName, out JsonElement value)
            || !value.TryGetInt32(out int result)
            || result <= 0)
        {
            throw new InvalidDataException($"FFprobe returned an invalid video {propertyName}.");
        }

        return result;
    }

    private static double ReadFrameRate(JsonElement stream)
    {
        foreach (string propertyName in new[] { "avg_frame_rate", "r_frame_rate" })
        {
            if (!stream.TryGetProperty(propertyName, out JsonElement value))
            {
                continue;
            }

            string? text = value.GetString();
            if (TryParseRational(text, out double result) && result > 0 && double.IsFinite(result))
            {
                return result;
            }
        }

        return DefaultFramesPerSecond;
    }

    private static bool TryParseRational(string? value, out double result)
    {
        result = 0;
        if (string.IsNullOrWhiteSpace(value))
        {
            return false;
        }

        string[] parts = value.Split('/', 2, StringSplitOptions.TrimEntries);
        if (!double.TryParse(parts[0], NumberStyles.Float, CultureInfo.InvariantCulture, out double numerator))
        {
            return false;
        }

        if (parts.Length == 1)
        {
            result = numerator;
            return true;
        }

        if (!double.TryParse(parts[1], NumberStyles.Float, CultureInfo.InvariantCulture, out double denominator)
            || denominator == 0)
        {
            return false;
        }

        result = numerator / denominator;
        return true;
    }

    private static TimeSpan ReadDuration(JsonElement stream, JsonElement root)
    {
        if (TryReadSeconds(stream, "duration", out TimeSpan streamDuration))
        {
            return streamDuration;
        }

        if (root.TryGetProperty("format", out JsonElement format)
            && TryReadSeconds(format, "duration", out TimeSpan formatDuration))
        {
            return formatDuration;
        }

        return TimeSpan.Zero;
    }

    private static bool TryReadSeconds(JsonElement element, string propertyName, out TimeSpan duration)
    {
        duration = TimeSpan.Zero;
        if (!element.TryGetProperty(propertyName, out JsonElement value))
        {
            return false;
        }

        double seconds;
        if (value.ValueKind == JsonValueKind.Number)
        {
            if (!value.TryGetDouble(out seconds))
            {
                return false;
            }
        }
        else if (!double.TryParse(value.GetString(), NumberStyles.Float, CultureInfo.InvariantCulture, out seconds))
        {
            return false;
        }

        if (!double.IsFinite(seconds) || seconds <= 0)
        {
            return false;
        }

        duration = TimeSpan.FromSeconds(seconds);
        return true;
    }

    private static int ReadRotation(JsonElement stream)
    {
        if (stream.TryGetProperty("side_data_list", out JsonElement sideData)
            && sideData.ValueKind == JsonValueKind.Array)
        {
            foreach (JsonElement entry in sideData.EnumerateArray())
            {
                if (entry.TryGetProperty("rotation", out JsonElement rotation)
                    && TryReadRotationValue(rotation, out int result))
                {
                    return result;
                }
            }
        }

        if (stream.TryGetProperty("tags", out JsonElement tags)
            && tags.TryGetProperty("rotate", out JsonElement tagRotation)
            && TryReadRotationValue(tagRotation, out int tagResult))
        {
            return tagResult;
        }

        return 0;
    }

    private static bool TryReadRotationValue(JsonElement element, out int rotation)
    {
        if (element.ValueKind == JsonValueKind.Number)
        {
            return element.TryGetInt32(out rotation);
        }

        return int.TryParse(element.GetString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out rotation);
    }

    private static int NormalizeRotation(int rotation)
    {
        int normalized = ((rotation % 360) + 360) % 360;
        return normalized switch
        {
            >= 45 and < 135 => 90,
            >= 135 and < 225 => 180,
            >= 225 and < 315 => 270,
            _ => 0
        };
    }
}
